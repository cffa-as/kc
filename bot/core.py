"""Bot核心模块"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import Optional

import websockets

from ai import AISummarizer
from rank import RankQuery
from config import Config
from utils import Logger, Censor


# AI 配置（从 config.json 读取）
AI_API_KEY = ""
AI_BASE_URL = "https://api.deepseek.com"
AI_MODEL_NAME = "deepseek-v4"


class GameBot:
    """游戏机器人核心类"""

    SERVERS = [
        ("wss://kg3.ss911.cn:6103/", "https://t1.ss911.cn"),
        ("wss://kg2.ss911.cn:6102/", "https://t1.ss911.cn"),
        ("wss://kg4.ss911.cn:6104/", "https://t1.ss911.cn"),
        ("wss://kg1.ss911.cn:6101/", "https://t1.ss911.cn"),
    ]

    def __init__(self, url: str, origin: str = "https://t1.ss911.cn"):
        self.url = url
        self.origin = origin
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.log = Logger()
        self.config = Config()
        self.censor = Censor()
        self.rank_query = RankQuery()
        # 加载 AI 配置
        self._ai_api_key = self.config.get("ai_api_key", "") or AI_API_KEY
        self._ai_base_url = self.config.get("ai_base_url", "") or AI_BASE_URL
        self._ai_model = self.config.get("ai_model", "") or AI_MODEL_NAME
        self.ai_summarizer = AISummarizer(self._ai_api_key, self._ai_base_url, self._ai_model)

        # 加载配置
        self._allowed_users = set(self.config.get("allowed_users", []))
        self._owners = set(self.config.get("owners", []))
        # 状态
        self._star_reminder = self.config.get("star_reminder", False)
        self._star_reminder_task = None
        self._star_reminder_sent_today = set()
        self._bot_name = ""
        self._my_user_id = ""
        self._last_summary_time = 0
        self._last_heartbeat = time.time()
        self._servers = self.SERVERS
        self._current_server_index = 0
        self._join_fail_count = 0
        self._player_query_handlers = {}
        self._login_token = ""
        self._room_query_pending = None  # 当前是否有查房在进行
        self._kicked_by_backup = False  # 是否因备用服务器查房被踢下线

        # 初始化处理器
        from bot.handlers import MessageDispatcher, RankHandler, AIHandler, RoomHandler, CrackHandler, UserHandler
        self.handlers = {
            'dispatcher': MessageDispatcher(self),
            'rank': RankHandler(self),
            'ai': AIHandler(self),
            'room': RoomHandler(self),
            'crack': CrackHandler(self),
            'user': UserHandler(self),
        }

    def _open_log(self):
        """打开日志文件"""
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
        self.log = Logger(log_path, self.config.get("log_filters", []))

    def _log(self, msg: str):
        """记录日志"""
        self.log.log(msg)

    # ==================== 配置管理 ====================

    def _load_config(self) -> dict:
        """加载配置文件"""
        return self.config.load()

    def get_fixed_room(self) -> str:
        """获取固定房间号"""
        return self.config.get("fixed_room", "")

    def set_fixed_room(self, room_id: str):
        """设置固定房间号"""
        self.config.set("fixed_room", room_id)
        self._log(f"已设置固定房间: {room_id}")

    def clear_fixed_room(self):
        """清除固定房间号"""
        self.config.delete("fixed_room")
        self._log("已清除固定房间")

    def add_allowed_user(self, user_id: str):
        """添加权限用户"""
        self._allowed_users.add(user_id)
        self.config.set("allowed_users", list(self._allowed_users))
        self._log(f"已添加权限用户: {user_id}")

    def remove_allowed_user(self, user_id: str):
        """删除权限用户"""
        if user_id in self._allowed_users:
            self._allowed_users.remove(user_id)
            self.config.set("allowed_users", list(self._allowed_users))
            self._log(f"已删除权限用户: {user_id}")

    def is_allowed_user(self, user_id: str) -> bool:
        """检查用户是否有权限"""
        return str(user_id) in self._allowed_users or str(user_id) in [str(u) for u in self._allowed_users]

    # ==================== 明星提醒 ====================

    async def toggle_star_reminder(self, enable: bool):
        """开启/关闭明星提醒"""
        self._star_reminder = enable
        self.config.set("star_reminder", enable)
        self._log(f"明星提醒: {'开启' if enable else '关闭'}")
        if enable:
            await self._start_star_reminder()
        else:
            await self._stop_star_reminder()

    async def _start_star_reminder(self):
        if self._star_reminder_task:
            self._star_reminder_task.cancel()
        self._star_reminder_task = asyncio.create_task(self._star_reminder_loop())

    async def _stop_star_reminder(self):
        if self._star_reminder_task:
            self._star_reminder_task.cancel()
            self._star_reminder_task = None

    async def _star_reminder_loop(self):
        """明星提醒循环"""
        last_date = None
        while self.running and self._star_reminder:
            now = datetime.now()
            today = now.date()
            if last_date != today:
                self._star_reminder_sent_today = set()
                last_date = today

            hour, minute, second = now.hour, now.minute, now.second
            if 9 <= hour <= 23 and second <= 2:
                key = (hour, minute)
                if key not in self._star_reminder_sent_today:
                    if minute == 2:
                        await self.send_msg("明星还有3分钟", "#FF69B4")
                        self._star_reminder_sent_today.add(key)
                    elif minute == 3:
                        await self.send_msg("明星还有2分钟", "#FF69B4")
                        self._star_reminder_sent_today.add(key)
                    elif minute == 4:
                        await self.send_msg("明星还有1分钟", "#FF69B4")
                        self._star_reminder_sent_today.add(key)
            await asyncio.sleep(1)

    # ==================== 固定房间 ====================

    async def _join_fixed_room(self):
        """进入固定房间"""
        fixed_room = self.get_fixed_room()
        if fixed_room:
            await self.send({"RoomId": fixed_room, "Password": "", "c": "JoinRoom"})
            self._log(f"进入固定房间: {fixed_room}")

    async def handle_change_site(self, site: str):
        """处理换位请求"""
        self._log(f"换位到: {site}")

        await self.send({"Site": "-1", "FSite": "", "c": "ChangeSite"})
        self._log(f"发送上树")
        await asyncio.sleep(0.3)

        await self.send({"Site": site, "c": "ChangeSite"})
        self._log(f"发送换位: {site}")

    # ==================== 连接管理 ====================

    async def connect(self) -> bool:
        """连接服务器"""
        try:
            self.ws = await websockets.connect(
                self.url,
                origin=self.origin,
                user_agent_header="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            self.running = True
            self._log(f"✓ 已连接: {self.url}")
            return True
        except Exception as e:
            self._log(f"✗ 连接失败: {e}")
            return False

    async def send(self, data: dict):
        """发送JSON"""
        if data.get("c") == "SayInRoom" and "Msg" in data:
            data["Msg"] = self.censor.censor(data["Msg"])
        msg = json.dumps(data, ensure_ascii=False)
        await self.ws.send(msg)
        self._log(f"→ {msg}")

    async def send_raw(self, msg: str):
        """发送原始字符串"""
        await self.ws.send(msg)
        self._log(f"→ {msg}")

    async def send_msg(self, msg: str, color: str = "#FFFFFF"):
        """发送消息"""
        await self.send({"Act": "", "Color": color, "Msg": msg, "c": "SayInRoom"})

    def _parse_room_sync(self, msg: str) -> dict:
        """解析 SO_Sync 消息中的玩家信息"""
        import re
        result = {}
        if "Player" in msg:
            player_blocks = re.findall(r'\[1,"?(\d+)"?,\{(.*?)\}\]', msg, re.DOTALL)
            players = []
            for user_id, block in player_blocks:
                name_m = re.search(r'"UserName"\s*:\s*"([^"]+)"', block)
                site_m = re.search(r'"RoomSite"\s*:\s*(\d+)', block)
                if name_m and site_m:
                    players.append({
                        "UserId": user_id,
                        "UserName": name_m.group(1),
                        "RoomSite": int(site_m.group(1))
                    })
            result["players"] = players
        return result

    async def login(self, token: str, device: str, p: str = ""):
        """登录"""
        self._login_token = token
        self._login_device = device
        self._login_p = p
        await self.send({"i": token, "device": device, "p": p})
        await asyncio.sleep(0.3)
        await self.send({"c": "UserInfo"})
        await asyncio.sleep(0.3)
        await self.send({"c": "JoinHall"})
        await self._join_fixed_room()
        if self._star_reminder:
            await self._start_star_reminder()

    # ==================== 主循环 ====================

    async def run(self):
        """主运行循环"""
        self._log("⏳ 开始监听... (输入内容发送，空行心跳)")
        self._log("-" * 50)

        async def recv_loop():
            """接收消息循环"""
            while self.running:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    self._log(f"← {msg}")
                    await self._process_message(msg)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    self._log(f"⚠ 连接关闭: {e}")
                    if not self.running:
                        break
                    await self._reconnect()
                except Exception as e:
                    self._log(f"错误: {e}")

        async def input_loop():
            """用户输入循环"""
            loop = asyncio.get_event_loop()
            while self.running:
                try:
                    line = await loop.run_in_executor(None, input, "")
                    if not self.running:
                        break
                    await self._process_input(line)
                except EOFError:
                    break

        await asyncio.gather(recv_loop(), input_loop())

    async def _process_message(self, msg: str):
        """处理接收到的消息"""
        # 查房回调
        if msg.startswith("SO_Sync{"):
            m = re.search(r'"n"\s*:\s*"Player(\d+)"', msg)
            if m:
                room_id = m.group(1)
                if room_id in self._player_query_handlers:
                    self._player_query_handlers[room_id](msg)
            m2 = re.search(r'"n"\s*:\s*"Room(\d+)"', msg)
            if m2:
                room_id = m2.group(1)
                if room_id in self._player_query_handlers:
                    self._player_query_handlers[room_id](msg)

        # 记录机器人信息
        if msg.startswith("UserInfo{"):
            m = re.search(r'"UserName"\s*:\s*"([^"]+)"', msg)
            if m:
                self._bot_name = m.group(1)
                self._log(f"机器人名字: {self._bot_name}")
            uid_m = re.search(r'"UserId"\s*:\s*"?(\d+)"?', msg)
            if uid_m:
                self._my_user_id = uid_m.group(1)
                self._log(f"机器人userId: {self._my_user_id}")

        # 处理房间消息
        if msg.startswith("SM{") or msg.startswith("RoomSay{"):
            user_id = None
            if msg.startswith("RoomSay{"):
                m = re.search(r'"u"\s*:\s*\[\s*\d+\s*,\s*(\d+)', msg)
                if m:
                    user_id = m.group(1)
                    if len(self._allowed_users) > 0 and user_id not in self._allowed_users:
                        self._log(f"用户 {user_id} 不在权限列表中，跳过")
                        return

            m = re.search(r'"m"\s*:\s*"([^"]*)"', msg)
            if m:
                content = m.group(1)
                await self.handlers['dispatcher'].dispatch(content, user_id)

        # 处理破解响应
        fixed_room = self.get_fixed_room()
        crack_result = self._handle_crack_response(msg, fixed_room)
        if crack_result:
            if crack_result == "crack_failed":
                await self.send_msg("破解失败，未找到有效密码", "#FF0000")
            elif isinstance(crack_result, dict):
                if crack_result.get("action") == "try_password":
                    if crack_result.get("delay"):
                        await asyncio.sleep(5)
                    await self.send(crack_result)
                elif crack_result.get("action") == "crack_success":
                    crack_room = self.handlers['dispatcher']._last_crack_room
                    password = crack_result['password']
                    fixed_room = crack_result['fixed_room']
                    
                    if crack_room:
                        await self.send({"RoomId": crack_room, "Password": "", "c": "JoinRoom"})
                        await asyncio.sleep(0.5)
                        await self.send_msg(f"房间{crack_room}密码: {password}", "#00FF00")
                        await asyncio.sleep(0.5)
                    
                    await self.send({"RoomId": fixed_room, "Password": password, "c": "JoinRoom"})
                    await asyncio.sleep(0.5)
                elif crack_result.get("action") == "heartbeat":
                    await self.send_raw("p")

        # 心跳
        now = time.time()
        if now - self._last_heartbeat >= 30:
            self._last_heartbeat = now
            await self.send_raw("p")

        # 处理jump消息
        if msg.startswith("jump{"):
            m = re.search(r'"r"\s*:\s*"?(\d+)"?', msg)
            l = re.search(r'"l"\s*:\s*"?(\d+)"?', msg)
            if m and l:
                jump_room, jump_line = m.group(1), l.group(1)
                self._join_fail_count += 1
                self._log(f"进房失败，jump到房间{jump_room}线路{jump_line}")
                if self._join_fail_count >= 1 and self._servers:
                    self._join_fail_count = 0
                    self._current_server_index = (self._current_server_index + 1) % len(self._servers)
                    ws_url, http_url = self._servers[self._current_server_index]
                    self.url = ws_url
                    self.origin = http_url
                    await self.ws.close()
                    await asyncio.sleep(1)
                    if await self.connect():
                        if not self._kicked_by_backup:
                            await self.login(self._login_token, self._login_device, self._login_p)
                        else:
                            self._log("因备用服务器查房被踢，等待查房流程接管")
                elif self._servers:
                    await asyncio.sleep(0.5)
                    await self.send({"RoomId": jump_room, "Password": "", "LineId": int(jump_line), "c": "JoinRoom"})

        # 处理邀请
        if msg.startswith("Invite{"):
            m = re.search(r'"FromUserName"\s*:\s*"([^"]*)"', msg)
            r = re.search(r'"RoomId"\s*:\s*"?(\d+)"?', msg)
            if m and r:
                username, room_id = m.group(1), r.group(1)
                reply = {"ToRoomId": room_id, "FromUserName": username, "c": "LeaveRoom"}
                await self.send(reply)

    async def _process_input(self, line: str):
        """处理用户输入"""
        if line.strip() == "":
            await self.send_raw("p")
            self._log("→ p (心跳)")
        elif line.startswith("{"):
            try:
                data = json.loads(line)
                await self.send(data)
            except json.JSONDecodeError:
                await self.send_raw(line)
        else:
            await self.handlers['dispatcher'].dispatch(line)

    async def reconnect_main_server(self, token: str, device: str, p: str) -> bool:
        """重新连接到主服务器并登录（查房后专用）"""
        retry_count = 0
        while retry_count < 10:
            try:
                ws_url, http_url = self._servers[self._current_server_index]
                self.url = ws_url
                self.origin = http_url
                self.ws = await websockets.connect(
                    ws_url,
                    origin=http_url,
                    user_agent_header="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                )
                self.running = True
                self._log(f"✓ 已连接到主服务器: {ws_url}")
                await self.send({"i": token, "device": device, "p": p})
                await asyncio.sleep(0.3)
                await self.send({"c": "UserInfo"})
                await asyncio.sleep(0.3)
                await self.send({"c": "JoinHall"})
                await self._join_fixed_room()
                if self._star_reminder:
                    await self._start_star_reminder()
                return True
            except Exception as e:
                retry_count += 1
                self._log(f"主服务器重连失败 ({retry_count}/10): {e}")
                await asyncio.sleep(2)
        self._log("主服务器重连超时")
        return False

    async def _reconnect(self):
        """重连"""
        self._log("⏳ 尝试重连...")
        await asyncio.sleep(3)
        if await self.connect():
            self._log("✓ 重连成功，重新登录...")
            # 如果是因为备用服务器查房被踢，不重新进入房间
            if not self._kicked_by_backup:
                await self.login(self._login_token, self._login_device, self._login_p)

    def _handle_crack_response(self, msg: str, fixed_room: str):
        """处理破解响应"""
        return self.handlers['crack']._handle_crack_response(msg)

    async def _delayed_return_to_room(self, room_id: str, password: str):
        """延迟回到房间"""
        await asyncio.sleep(5)
        await self.send({"RoomId": room_id, "Password": password, "c": "JoinRoom"})

    def close_log(self):
        """关闭日志"""
        self.log.close()
