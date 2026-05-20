"""用户处理器"""

import asyncio
import requests
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import GameBot


class UserHandler:
    """用户处理器"""

    U = "e87F44VUl3wjvWv0weqGL6sbfSojFBWQYTYd3KKvteI%3D"

    def __init__(self, bot: "GameBot"):
        self.bot = bot

    def _get_user_name(self, user_info: dict) -> str:
        return user_info.get("userName") or user_info.get("UserName") or "未知"

    def _get_user_info(self, sid: str) -> dict | None:
        try:
            data = requests.get(
                f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={self.U}",
                timeout=10
            ).json()
            return data.get("data", [None])[0] if data.get("msg") == "OK" else None
        except Exception:
            return None

    def _get_user_posts(self, user_id: str, limit: int = 10) -> list:
        try:
            return requests.get(
                f"https://t1.ss911.cn/Sns/PostUser.ss?userid={user_id}&p=1&ps={limit}&u={self.U}",
                timeout=10
            ).json().get("list", [])
        except Exception:
            return []

    def _build_prompt(self, user_name: str, posts: list, task_type: str) -> str:
        summary = "\n".join(
            f"[{p.get('addtime', '')}] {p.get('body', '')} (赞:{p.get('goodnum', 0)}, 评论:{p.get('replynum', 0)})"
            for p in posts[:10]
        )
        context = f"用户【{user_name}】{'的信息：' if task_type == 'analysis' else '的动态如下，请锐评：'}\n\n{summary}\n\n提示：点赞>100或评论>10属于高互动，点赞<10或评论<1属于低互动（可提及），其他情况忽略互动数据。"

        if task_type == "analysis":
            return context + """
请分析并回复以下内容（直接输出，不要标题）：
1. 人物画像：推断年龄段、性格特点、社交风格
2. MBTI预测：根据动态内容推断最可能的MBTI类型，给出简要理由
3. 兴趣/状态：从动态看出什么爱好和生活状态
4. 有趣细节：有什么有趣的发现

要求：简洁犀利，总字数300字以内。"""
        return context + "\n要求：毒舌犀利，阴阳怪气，调侃动态内容和风格。200字以内，一针见血。"

    async def _fetch_user(self, sid: str) -> tuple[str, str] | None:
        """获取用户ID和名称"""
        user_info = await asyncio.to_thread(self._get_user_info, sid)
        if not user_info:
            await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
            return None
        return user_info["userId"], self._get_user_name(user_info)

    async def _request_with_user(self, sid: str, url: str) -> tuple[bool, str]:
        """通用请求，成功返回(True, 用户名)，失败返回(False, 错误信息)"""
        result = await self._fetch_user(sid)
        if not result:
            return False, "未找到用户"
        user_id, user_name = result
        try:
            resp = await asyncio.to_thread(
                lambda: requests.get(f"{url}&fid={user_id}&u={self.U}", timeout=10).json()
            )
            msg = resp.get("msg", "未知错误")
            return True, f"{'已' if msg == 'OK' else ''}{msg} {user_name}"
        except Exception:
            return False, f"{url.split('type=')[1].split('&')[0]}失败: 网络错误"

    async def _analyze_or_roast(self, sid: str, task_type: str, color: str, title: str):
        result = await self._fetch_user(sid)
        if not result:
            return
        user_id, user_name = result

        posts = await asyncio.to_thread(self._get_user_posts, user_id)
        if not posts:
            await self.bot.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
            return

        await self.bot.send_msg(f"正在{title} {user_name}...", color)
        result_text = self.bot.ai_summarizer.direct_answer(self._build_prompt(user_name, posts, task_type))
        await self._send_long_message(f"【{user_name}】", color, prefix=True)
        await self._send_long_message(result_text, color)

    async def handle_analysis(self, sid: str):
        await self._analyze_or_roast(sid, "analysis", "#00FFFF", "分析")

    async def handle_roast(self, sid: str):
        await self._analyze_or_roast(sid, "roast", "#FF69B4", "锐评")

    async def handle_follow(self, sid: str):
        url = f"https://t1.ss911.cn/User/FriendDo.ss?type=3"
        ok, msg = await self._request_with_user(sid, url)
        await self.bot.send_msg(msg, "#00FF00" if ok and msg.startswith("已") else "#FF0000")

    async def handle_unfollow(self, sid: str):
        url = f"https://t1.ss911.cn/User/FriendDo.ss?type=4&both=1"
        ok, msg = await self._request_with_user(sid, url)
        await self.bot.send_msg(msg, "#00FF00" if ok and msg.startswith("已") else "#FF0000")

    async def _send_long_message(self, msg: str, color: str, prefix: bool = False):
        if prefix:
            await self.bot.send_msg(msg, color)
        else:
            for line in msg.split("\n"):
                if line.strip():
                    for i in range(0, len(line), 150):
                        await self.bot.send_msg(line[i:i + 150], color)
                        await asyncio.sleep(1.5)
