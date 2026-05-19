"""AI处理器"""

import asyncio
import re
import json
from typing import TYPE_CHECKING

from utils import filter_messages_by_time, split_message

if TYPE_CHECKING:
    from ..core import GameBot


import os


class AIHandler:
    """AI处理器"""

    def __init__(self, bot: "GameBot"):
        self.bot = bot
        self._last_summary_time = 0

    def _get_log_path(self) -> str:
        """获取日志文件路径"""
        if hasattr(self.bot, 'log_path'):
            return self.bot.log_path
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.log")

    def _read_speaker_messages(self, minutes: int = 5) -> list:
        """从日志文件读取喇叭消息"""
        messages = []
        log_file = self._get_log_path()

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    match = re.match(r'\[(\d{2}:\d{2}:\d{2})\] ← Speaker\{', line)
                    if not match:
                        continue

                    timestamp_str = match.group(1)
                    json_start = line.find("Speaker{")
                    if json_start == -1:
                        continue
                    json_str = line[json_start + 7:]

                    try:
                        data = json.loads(json_str)
                        msg = data.get("Msg", "")
                        user_name = data.get("UserName", "未知")

                        if user_name == self.bot._bot_name:
                            continue
                        if msg in ["功能列表", "1.查周榜/查月榜+道具名(可选)", "2.喇叭总结/喇叭提问+分钟数(可选)",
                                   "3.破解+房间号", "4.查房+房间号", "5.AI+问题", "6.固定房间+房号"]:
                            continue
                        if msg:
                            messages.append({"timestamp": timestamp_str, "userName": user_name, "msg": msg})
                    except:
                        continue
        except Exception as e:
            self.bot._log(f"读取喇叭消息失败: {e}")
            return []

        # 过滤时间
        recent_messages = filter_messages_by_time(messages, minutes)
        return [{"userName": m["userName"], "msg": m["msg"]} for m in recent_messages]

    def _read_room_messages(self, minutes: int = 5, user_id: str = None) -> list:
        """从日志文件读取房间消息"""
        messages = []
        log_file = self._get_log_path()

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    match = re.match(r'\[(\d{2}:\d{2}:\d{2})\] ← RoomSay', line)
                    if not match:
                        continue

                    timestamp_str = match.group(1)
                    json_start = line.find("RoomSay{")
                    if json_start == -1:
                        continue
                    json_str = line[json_start + 7:]

                    try:
                        data = json.loads(json_str)
                        site = data.get("s", 0)
                        user_data = data.get("u", [])
                        msg_content = data.get("m", "")

                        if len(user_data) >= 3:
                            username = user_data[2]
                        else:
                            username = "未知玩家"
                        uid = str(user_data[1]) if len(user_data) >= 2 else ""

                        if username == self.bot._bot_name:
                            continue

                        if user_id and uid != user_id:
                            continue

                        if msg_content:
                            messages.append({
                                "timestamp": timestamp_str,
                                "site": site,
                                "userName": username,
                                "userId": uid,
                                "msg": msg_content
                            })
                    except:
                        continue
        except Exception as e:
            self.bot._log(f"读取房间消息失败: {e}")
            return []

        # 过滤时间
        recent_messages = filter_messages_by_time(messages, minutes)
        return [{"timestamp": m.get("timestamp", ""), "site": m["site"], "userName": m["userName"], "userId": m["userId"], "msg": m["msg"]} for m in recent_messages]

    def _read_room_messages_by_count(self, count: int = 10, user_id: str = None) -> list:
        """从日志文件读取最近N条房间消息"""
        messages = self._read_room_messages(minutes=9999, user_id=user_id)
        return [{"timestamp": m["timestamp"], "site": m["site"], "userName": m["userName"], "userId": m["userId"], "msg": m["msg"]} for m in
                messages[-count:]]

    async def handle_ai_summary(self, content: str):
        """处理总结喇叭请求"""
        match = re.search(r'(总结喇叭|喇叭总结)(\d+)', content)
        minutes = int(match.group(2)) if match else 5

        messages = self._read_speaker_messages(minutes)
        if not messages:
            await self.bot.send_msg(f"最近{minutes}分钟暂无喇叭消息", "#FFA500")
            return

        await self.bot.send_msg(f"正在总结最近{minutes}分钟的{len(messages)}条喇叭...", "#00FF00")
        summary = self.bot.ai_summarizer.summarize(messages, minutes)
        for line in summary.split("\n"):
            if not line.strip():
                continue
            for part in split_message(line, 150):
                await self.bot.send_msg(part, "#00FFFF")
                await asyncio.sleep(1.5)

    async def handle_ai_question(self, content: str):
        """处理喇叭提问请求"""
        question = content.replace("喇叭提问", "").replace("提问喇叭", "").strip()
        if not question:
            await self.bot.send_msg("请输入要查询的问题，如：喇叭提问有没有人征婚", "#FFA500")
            return

        minutes = 60
        messages = self._read_speaker_messages(minutes)
        if not messages:
            await self.bot.send_msg(f"最近{minutes}分钟暂无喇叭消息", "#FFA500")
            return

        await self.bot.send_msg(f"正在查询最近{minutes}分钟的喇叭...", "#00FF00")
        answer = self.bot.ai_summarizer.answer_question(messages, question, minutes)
        for line in answer.split("\n"):
            if not line.strip():
                continue
            for part in split_message(line, 150):
                await self.bot.send_msg(part, "#00FFFF")
                await asyncio.sleep(1.5)

    async def handle_ai_chat(self, content: str):
        """处理AI直接回答请求"""
        question = content.replace("AI", "").strip()
        if not question:
            await self.bot.send_msg("请输入要查询的问题，如：AI今天天气怎么样", "#FFA500")
            return

        await self.bot.send_msg(f"正在思考...", "#00FF00")
        answer = self.bot.ai_summarizer.direct_answer(question)
        for line in answer.split("\n"):
            if not line.strip():
                continue
            for part in split_message(line, 150):
                await self.bot.send_msg(part, "#00FFFF")
                await asyncio.sleep(1.5)

    async def handle_room_summary(self, minutes: int = 5):
        """处理总结房间消息请求"""
        import time
        now = time.time()
        if now - self._last_summary_time < 10:
            await self.bot.send_msg(f"操作太频繁，请{int(10 - (now - self._last_summary_time))}秒后再试", "#FFA500")
            return
        self._last_summary_time = now

        messages = self._read_room_messages(minutes)
        if not messages:
            await self.bot.send_msg(f"最近{minutes}分钟暂无房间消息", "#FFA500")
            return

        await self.bot.send_msg(f"正在总结最近{minutes}分钟的{len(messages)}条消息...", "#00FF00")
        summary = self.bot.ai_summarizer.summarize_room_messages(messages, minutes)
        for line in summary.split("\n"):
            if not line.strip():
                continue
            for part in split_message(line, 150):
                await self.bot.send_msg(part, "#00FFFF")
                await asyncio.sleep(1.5)

    async def handle_chat_history(self, count: int = 10, user_id: str = None):
        """处理聊天记录请求"""
        import time
        now = time.time()
        if now - self._last_summary_time < 5:
            await self.bot.send_msg(f"操作太频繁，请{int(5 - (now - self._last_summary_time))}秒后再试", "#FFA500")
            return
        self._last_summary_time = now

        messages = self._read_room_messages_by_count(count, user_id)
        if not messages:
            filter_msg = f"用户ID {user_id}" if user_id else ""
            await self.bot.send_msg(f"{filter_msg}暂无聊天记录", "#FFA500")
            return

        filter_msg = f"【{messages[0]['userName']}的最近{len(messages)}条记录】" if user_id else f"【最近{len(messages)}条聊天记录】"
        await self.bot.send_msg(filter_msg, "#FFFF00")
        await asyncio.sleep(0.5)

        for msg in messages:
            timestamp = msg["timestamp"]
            username = msg["userName"]
            content = msg["msg"]
            msg_text = f"{timestamp} {username}：{content}"

            if len(msg_text) <= 150:
                await self.bot.send_msg(msg_text, "#00FFFF")
            else:
                for part in split_message(msg_text, 150):
                    await self.bot.send_msg(part, "#00FFFF")
            await asyncio.sleep(1.5)

    async def handle_chat_question(self, question: str, user_id: str = None):
        """处理聊天记录提问"""
        import time
        if not question:
            await self.bot.send_msg("请输入问题，如：记录提问这个人最近聊了什么", "#FFA500")
            return

        now = time.time()
        if now - self._last_summary_time < 10:
            await self.bot.send_msg(f"操作太频繁，请{int(10 - (now - self._last_summary_time))}秒后再试", "#FFA500")
            return
        self._last_summary_time = now

        # 读取最近100条消息
        messages = self._read_room_messages_by_count(100, user_id)
        if not messages:
            filter_msg = f"用户ID {user_id}" if user_id else "最近100条"
            await self.bot.send_msg(f"{filter_msg}暂无聊天记录", "#FFA500")
            return

        filter_msg = f"[{messages[0]['userName']}]" if user_id else ""
        await self.bot.send_msg(f"正在分析{filter_msg}聊天记录...", "#00FF00")
        answer = self.bot.ai_summarizer.answer_room_question(messages, question, len(messages))
        for line in answer.split("\n"):
            if not line.strip():
                continue
            for part in split_message(line, 150):
                await self.bot.send_msg(part, "#00FFFF")
                await asyncio.sleep(1.5)
