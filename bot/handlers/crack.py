"""房间破解处理器"""

import asyncio
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..core import GameBot

import requests


class CrackHandler:
    """破解房间处理器"""

    U = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"
    FOLLOW_U = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

    def __init__(self, bot: "GameBot"):
        self.bot = bot
        self._room_cracking = False
        self._crack_pending = None

    async def handle_crack(self, room_id: str):
        """处理破解房间请求"""
        if self._room_cracking:
            await self.bot.send_msg("正在破解中，请稍后...", "#FFA500")
            return

        self._room_cracking = True
        self._crack_pending = {
            "room_id": room_id,
            "stage": 1,
            "current_password": 0
        }
        await self.bot.send_msg(f"开始破解房间 {room_id}...", "#00FF00")

        # 发送第一个密码尝试 (000)
        password = "000"
        self.bot._log(f"尝试密码: {password}")
        await self.bot.send({"RoomId": room_id, "Password": password, "c": "JoinRoom"})

    def _handle_crack_response(self, msg: str):
        """处理破解响应，在 recv_loop 中调用"""
        if not self._room_cracking or not self._crack_pending:
            return None

        room_id = self._crack_pending["room_id"]
        stage = self._crack_pending.get("stage", 1)

        if "InvalidPassword" in msg:
            room_match = re.search(r'"RoomId"\s*:\s*"?(\d+)"?', msg)
            if room_match and room_match.group(1) != room_id:
                return None

            self._crack_pending["current_password"] += 1

            if stage == 1:
                if self._crack_pending["current_password"] >= 1000:
                    self._crack_pending["current_password"] = 0
                    self._crack_pending["stage"] = 2
                    password = "0"
                    self.bot._log(f"阶段1完成，进入阶段2: 尝试密码: {password}")
                    return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom", "delay": True}
                password = f"{self._crack_pending['current_password']:03d}"
            elif stage == 2:
                if self._crack_pending["current_password"] >= 10:
                    self._crack_pending["current_password"] = 0
                    self._crack_pending["stage"] = 3
                    password = "00"
                    self.bot._log(f"阶段2完成，进入阶段3: 尝试密码: {password}")
                    return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom", "delay": True}
                password = f"{self._crack_pending['current_password']}"
            elif stage == 3:
                if self._crack_pending["current_password"] >= 100:
                    self._room_cracking = False
                    self._crack_pending = None
                    return "crack_failed"
                password = f"{self._crack_pending['current_password']:02d}"

            if self._crack_pending["current_password"] > 0 and self._crack_pending["current_password"] % 50 == 0:
                return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom", "delay": True}

            self.bot._log(f"尝试密码: {password}")
            return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom"}

        elif msg.startswith("JoinRoom"):
            room_match = re.search(r'"RoomId"\s*:\s*"?(\d+)"?', msg)
            if room_match and room_match.group(1) == room_id:
                if stage == 1:
                    password = f"{self._crack_pending['current_password']:03d}"
                elif stage == 2:
                    password = f"{self._crack_pending['current_password']}"
                else:
                    password = f"{self._crack_pending['current_password']:02d}"

                self.bot._log(f"破解成功! 密码: {password}")
                fixed_room = self.bot.get_fixed_room()
                self._room_cracking = False
                self._crack_pending = None
                return {"action": "crack_success", "fixed_room": fixed_room, "password": password}

        elif msg == "p":
            return {"action": "heartbeat"}

        return None

    def stop_crack(self):
        """停止破解"""
        self._room_cracking = False
        self._crack_pending = None
