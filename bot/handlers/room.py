"""房间处理器"""

import asyncio
import json
import re
import websockets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import GameBot


class RoomHandler:
    """房间处理器"""

    def __init__(self, bot: "GameBot"):
        self.bot = bot

    async def handle_room_query(self, room_id: str):
        """处理查房请求"""
        self.bot._log(f"处理查房请求: {room_id}")

        current_room = self.bot._current_followed_room or self.bot.get_fixed_room()
        token = getattr(self.bot, '_login_token', '')
        device = getattr(self.bot, '_login_device', '')
        p = getattr(self.bot, '_login_p', '')

        if not token:
            try:
                await self.bot.send_msg("查房失败：未登录", "#FF0000")
            except Exception:
                pass
            return

        result = None
        success = False
        used_backup_server = False

        result = await self._query_on_current_connection(room_id)

        if result.get("players"):
            success = True
        else:
            self.bot._log("当前连接查不到，尝试备用服务器...")
            if self.bot._servers:
                for i, (ws_url, http_url) in enumerate(self.bot._servers):
                    if i == self.bot._current_server_index:
                        continue
                    try:
                        result = await self._query_on_server(ws_url, http_url, room_id, token, device, p)
                        if result.get("players"):
                            success = True
                            used_backup_server = True
                            self.bot._kicked_by_backup = True
                            self.bot._log(f"备用服务器{ws_url}查房成功")
                            break
                    except Exception as e:
                        self.bot._log(f"服务器{ws_url}查询失败: {e}")
                        continue

        # 如果用了备用服务器，需要等待主连接恢复并回到原来房间
        if used_backup_server and current_room:
            self.bot._log("等待主连接断开...")
            # 等待足够时间让主连接被踢下线
            await asyncio.sleep(5)
            # 立即标记，防止 jump 消息触发多余的连接切换
            self.bot._kicked_by_backup = True
            self.bot._log("等待主连接恢复...")
            # 重连主服务器
            if await self.bot.reconnect_main_server(token, device, p):
                self.bot._log(f"查房完成，回到房间: {current_room}")
                await self.bot.send({"RoomId": current_room, "Password": "", "c": "JoinRoom"})
                await asyncio.sleep(0.2)
            # 清理标记
            self.bot._kicked_by_backup = False

        # 回复结果
        if success and result:
            room_info = result.get("room_info", {})
            players = result.get("players", [])
            msg = self._format_room_info(room_id, room_info, players)
            try:
                await self.bot.send_msg(msg, "#00FF00")
            except Exception as e:
                self.bot._log(f"回复查房结果失败: {e}")
        else:
            try:
                await self.bot.send_msg(f"房间{room_id}查房失败", "#FF0000")
            except Exception as e:
                self.bot._log(f"回复查房失败: {e}")

    def _format_room_info(self, room_id: str, room_info: dict, players: list) -> str:
        """格式化房间信息"""
        lines = []

        locked = room_info.get("Locked", False)
        room_master = room_info.get("RoomMaster", 0)
        player_num = room_info.get("PlayerNum", len(players))
        double_integral = room_info.get("DoubleIntegral", False)
        limit_integral = room_info.get("LimitIntegral", 0)
        voice_users = room_info.get("VoiceUser", [])

        user_id_to_name = {str(pl.get("UserId", "")): pl.get("UserName", "未知") for pl in players}

        lines.append(f"房间{room_id} {'🔒已锁' if locked else '🔓未锁'}")
        lines.append(f"房主: {user_id_to_name.get(str(room_master), f'ID:{room_master}')}")
        lines.append(f"人数: {player_num}/20")
        lines.append(f"双倍积分: {'是' if double_integral else '否'}")
        if limit_integral:
            lines.append(f"限制积分: {limit_integral}")
        if voice_users:
            voice_names = []
            for uid in voice_users:
                name = user_id_to_name.get(str(uid))
                if name:
                    voice_names.append(name)
            if voice_names:
                lines.append(f"开麦: {', '.join(voice_names)}")
        else:
            lines.append("开麦: 无")
        if players:
            sorted_players = sorted(players, key=lambda pl: pl.get('RoomSite', 999))
            player_list = [f"[{pl['RoomSite']}]{pl['UserName']}" for pl in sorted_players]
            lines.append(f"玩家: {', '.join(player_list)}")

        return " / ".join(lines)

    async def _query_on_current_connection(self, room_id: str) -> dict:
        """用当前连接同时查询房间信息和玩家列表"""
        self.bot._log(f"用当前连接查询房间: {room_id}")

        room_event = asyncio.Event()
        player_event = asyncio.Event()
        room_info = {}
        players = []

        def sync_callback(msg: str):
            self._parse_sync(msg, room_id, room_info, players, room_event, player_event)

        self.bot._player_query_handlers[room_id] = sync_callback

        try:
            await self.bot.ws.send(json.dumps({"c": "SO_o", "n": f"Room{room_id}"}))
            await self.bot.ws.send(json.dumps({"c": "SO_o", "n": f"Player{room_id}"}))

            try:
                await asyncio.wait_for(
                    asyncio.gather(room_event.wait(), player_event.wait()),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            self.bot._log(f"→ 当前连接查房失败: {type(e).__name__}: {e}")

        finally:
            self.bot._player_query_handlers.pop(room_id, None)

        return {"room_info": room_info, "players": players}

    def _parse_sync(self, msg: str, room_id: str, room_info: dict, players: list, room_event: asyncio.Event, player_event: asyncio.Event):
        """解析 SO_Sync 消息"""
        if not msg.startswith("SO_Sync"):
            return
        try:
            json_str = msg[len("SO_Sync"):]
            data = json.loads(json_str)
            n = data.get("n", "")
            l = data.get("l", [])

            if n == f"Room{room_id}":
                for item in l:
                    if len(item) >= 3 and item[0] == 1:
                        room_info[str(item[1])] = item[2]
                room_event.set()

            elif n == f"Player{room_id}":
                for item in l:
                    flag = item[0]
                    if flag == 1 and len(item) >= 3 and isinstance(item[2], dict):
                        player_data = item[2]
                        players.append({
                            "UserId": str(item[1]),
                            "UserName": player_data.get("UserName", "未知"),
                            "RoomSite": player_data.get("RoomSite", 0)
                        })
                player_event.set()

        except Exception as e:
            self.bot._log(f"_parse_sync error: {e}")

    async def _query_on_server(self, ws_url: str, http_url: str, room_id: str, token: str, device: str, p: str) -> dict:
        """在单个服务器上查询"""
        self.bot._log(f"[{ws_url}] 开始查房: room={room_id}")
        try:
            async with websockets.connect(ws_url, additional_headers={"Origin": http_url}) as ws:
                await ws.send(json.dumps({"i": token, "device": device, "p": p}))

                for _ in range(10):
                    try:
                        resp = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        if "Login" in resp:
                            break
                    except asyncio.TimeoutError:
                        continue

                await ws.send(json.dumps({"c": "UserInfo"}))
                await asyncio.sleep(0.3)

                room_event = asyncio.Event()
                player_event = asyncio.Event()
                room_info = {}
                players = []

                result = {"room_info": {}, "players": []}

                async def listener():
                    try:
                        while not (room_event.is_set() and player_event.is_set()):
                            try:
                                resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                                self._parse_sync(resp, room_id, room_info, players, room_event, player_event)
                            except asyncio.TimeoutError:
                                if room_event.is_set() and player_event.is_set():
                                    break
                    except Exception:
                        pass

                listener_task = asyncio.create_task(listener())
                await asyncio.sleep(0.1)

                await ws.send(json.dumps({"c": "SO_o", "n": f"Room{room_id}"}))
                await ws.send(json.dumps({"c": "SO_o", "n": f"Player{room_id}"}))

                try:
                    await asyncio.wait_for(
                        asyncio.gather(room_event.wait(), player_event.wait()),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    pass

                result["room_info"] = room_info
                result["players"] = players
                listener_task.cancel()
                return result

        except Exception as e:
            self.bot._log(f"[{ws_url}] 查房异常: {e}")
            return {"room_info": {}, "players": []}
