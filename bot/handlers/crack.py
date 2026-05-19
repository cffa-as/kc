"""房间破解和用户处理器"""

import asyncio
import re
from typing import TYPE_CHECKING

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


class UserHandler:
    """用户处理器"""

    U = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"
    FOLLOW_U = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

    def __init__(self, bot: "GameBot"):
        self.bot = bot

    async def handle_analysis(self, sid: str):
        """分析用户动态 + MBTI预测"""
        myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={self.U}"

        try:
            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info.get("userName") or user_info.get("UserName") or "未知"
            integral = user_info.get("integral", "")
            online = "在线" if user_info.get("online") == 2 else "离线"
            is_boy = "男" if user_info.get("isboy", True) else "女"

            post_url = f"https://t1.ss911.cn/Sns/PostUser.ss?userid={user_id}&p=1&ps=10&u={self.U}"
            response = await asyncio.to_thread(requests.get, post_url, timeout=10)
            posts_data = response.json()

            if not posts_data.get("list"):
                await self.bot.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
                return

            posts = posts_data["list"]
            posts_text = []
            for post in posts[:10]:
                body = post.get("body", "")
                addtime = post.get("addtime", "")
                goodnum = post.get("goodnum", 0)
                replynum = post.get("replynum", 0)
                posts_text.append(f"[{addtime}] {body} (赞:{goodnum}, 评论:{replynum})")

            posts_summary = "\n".join(posts_text)

            prompt = f"""用户【{user_name}】的信息：
- 性别: {is_boy}
- 积分: {integral}
- 在线: {online}

最近动态：
{posts_summary}

提示：点赞>100或评论>10属于高互动，点赞<10或评论<1属于低互动（可提及），其他情况忽略互动数据。

请分析并回复以下内容（直接输出，不要标题）：
1. 人物画像：推断年龄段、性格特点、社交风格
2. MBTI预测：根据动态内容推断最可能的MBTI类型，给出简要理由
3. 兴趣/状态：从动态看出什么爱好和生活状态
4. 有趣细节：有什么有趣的发现

要求：简洁犀利，总字数150字以内。"""

            await self.bot.send_msg(f"正在分析 {user_name}...", "#00FFFF")
            result = self.bot.ai_summarizer.direct_answer(prompt)
            await self.bot.send_msg(f"【{user_name}】", "#00FF00")
            for line in result.split("\n"):
                if not line.strip():
                    continue
                for i in range(0, len(line), 150):
                    await self.bot.send_msg(line[i:i + 150], "#00FF00")
                    await asyncio.sleep(1.5)

        except Exception as e:
            await self.bot.send_msg(f"分析失败: {e}", "#FF0000")

    async def handle_roast(self, sid: str):
        """锐评用户动态"""
        url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={self.U}"

        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info.get("userName") or user_info.get("UserName") or "未知"

            post_url = f"https://t1.ss911.cn/Sns/PostUser.ss?userid={user_id}&p=1&ps=10&u={self.U}"
            response = await asyncio.to_thread(requests.get, post_url, timeout=10)
            posts_data = response.json()

            if not posts_data.get("list"):
                await self.bot.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
                return

            posts = posts_data["list"]
            posts_text = []
            for post in posts[:10]:
                body = post.get("body", "")
                addtime = post.get("addtime", "")
                goodnum = post.get("goodnum", 0)
                replynum = post.get("replynum", 0)
                posts_text.append(f"[{addtime}] {body} (赞:{goodnum}, 评论:{replynum})")

            posts_summary = "\n".join(posts_text)

            prompt = f"""用户【{user_name}】的动态如下，请锐评：

{posts_summary}

提示：点赞>100或评论>10属于高互动，点赞<10或评论<1属于低互动（可提及），其他情况忽略互动数据。

要求：毒舌犀利，阴阳怪气，调侃动态内容和风格。100字以内，一针见血。"""

            await self.bot.send_msg(f"正在锐评 {user_name}...", "#FF69B4")
            result = self.bot.ai_summarizer.direct_answer(prompt)
            await self.bot.send_msg(f"【{user_name}】", "#FF69B4")
            for line in result.split("\n"):
                if not line.strip():
                    continue
                for i in range(0, len(line), 150):
                    await self.bot.send_msg(line[i:i + 150], "#FF69B4")
                    await asyncio.sleep(1.5)

        except Exception as e:
            await self.bot.send_msg(f"锐评失败: {e}", "#FF0000")

    async def handle_follow(self, sid: str):
        """关注用户"""
        myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={self.U}"

        try:
            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info.get("userName") or user_info.get("UserName") or "未知"

            follow_url = f"https://t1.ss911.cn/User/FriendDo.ss?type=3&fid={user_id}&u={self.FOLLOW_U}"
            response = await asyncio.to_thread(requests.get, follow_url, timeout=10)
            result = response.json()

            if result.get("msg") == "OK":
                await self.bot.send_msg(f"已关注 {user_name}", "#FFFF00")
            else:
                await self.bot.send_msg(f"关注失败: {result.get('msg', '未知错误')}", "#FF0000")
        except Exception as e:
            await self.bot.send_msg(f"关注失败: {str(e)}", "#FF0000")

    async def handle_unfollow(self, sid: str):
        """取关用户"""
        myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={self.U}"

        try:
            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info.get("userName") or user_info.get("UserName") or "未知"

            unfollow_url = f"https://t1.ss911.cn/User/FriendDo.ss?type=4&fid={user_id}&both=1&u={self.FOLLOW_U}"
            response = await asyncio.to_thread(requests.get, unfollow_url, timeout=10)
            result = response.json()

            if result.get("msg") == "OK":
                await self.bot.send_msg(f"已取关 {user_name}", "#FFFF00")
            else:
                await self.bot.send_msg(f"取关失败: {result.get('msg', '未知错误')}", "#FF0000")
        except Exception as e:
            await self.bot.send_msg(f"取关失败: {str(e)}", "#FF0000")
