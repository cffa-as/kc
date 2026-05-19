"""用户处理器"""

import asyncio
import requests

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import GameBot


class UserHandler:
    """用户处理器"""

    U = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"
    FOLLOW_U = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

    def __init__(self, bot: "GameBot"):
        self.bot = bot

    def _get_user_info(self, sid: str) -> dict | None:
        """获取用户基本信息"""
        myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={self.U}"
        try:
            response = requests.get(myf_url, timeout=10)
            data = response.json()
            if data.get("msg") == "OK" and data.get("data"):
                return data["data"][0]
        except Exception as e:
            self.bot._log(f"获取用户信息失败: {e}")
        return None

    def _get_user_posts(self, user_id: str, limit: int = 10) -> list:
        """获取用户动态"""
        post_url = f"https://t1.ss911.cn/Sns/PostUser.ss?userid={user_id}&p=1&ps={limit}&u={self.U}"
        try:
            response = requests.get(post_url, timeout=10)
            data = response.json()
            return data.get("list", [])
        except Exception as e:
            self.bot._log(f"获取用户动态失败: {e}")
        return []

    def _format_posts(self, posts: list) -> str:
        """格式化动态列表"""
        posts_text = []
        for post in posts[:10]:
            body = post.get("body", "")
            addtime = post.get("addtime", "")
            goodnum = post.get("goodnum", 0)
            replynum = post.get("replynum", 0)
            posts_text.append(f"[{addtime}] {body} (赞:{goodnum}, 评论:{replynum})")
        return "\n".join(posts_text)

    async def handle_analysis(self, sid: str):
        """分析用户动态 + MBTI预测"""
        user_info = await asyncio.to_thread(self._get_user_info, sid)
        if not user_info:
            await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
            return

        user_id = user_info["userId"]
        user_name = user_info.get("userName") or user_info.get("UserName") or "未知"
        integral = user_info.get("integral", "")
        online = "在线" if user_info.get("online") == 2 else "离线"
        is_boy = "男" if user_info.get("isboy", True) else "女"

        posts = await asyncio.to_thread(self._get_user_posts, user_id)
        if not posts:
            await self.bot.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
            return

        posts_summary = self._format_posts(posts)

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
        await self._send_long_message(f"【{user_name}】", "#00FF00", prefix=True)
        await self._send_long_message(result, "#00FF00")

    async def handle_roast(self, sid: str):
        """锐评用户动态"""
        user_info = await asyncio.to_thread(self._get_user_info, sid)
        if not user_info:
            await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
            return

        user_id = user_info["userId"]
        user_name = user_info.get("userName") or user_info.get("UserName") or "未知"

        posts = await asyncio.to_thread(self._get_user_posts, user_id)
        if not posts:
            await self.bot.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
            return

        posts_summary = self._format_posts(posts)

        prompt = f"""用户【{user_name}】的动态如下，请锐评：

{posts_summary}

提示：点赞>100或评论>10属于高互动，点赞<10或评论<1属于低互动（可提及），其他情况忽略互动数据。

要求：毒舌犀利，阴阳怪气，调侃动态内容和风格。100字以内，一针见血。"""

        await self.bot.send_msg(f"正在锐评 {user_name}...", "#FF69B4")
        result = self.bot.ai_summarizer.direct_answer(prompt)
        await self._send_long_message(f"【{user_name}】", "#FF69B4", prefix=True)
        await self._send_long_message(result, "#FF69B4")

    async def handle_follow(self, sid: str):
        """关注用户"""
        user_info = await asyncio.to_thread(self._get_user_info, sid)
        if not user_info:
            await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
            return

        user_id = user_info["userId"]
        user_name = user_info.get("userName") or user_info.get("UserName") or "未知"

        follow_url = f"https://t1.ss911.cn/User/FriendDo.ss?type=3&fid={user_id}&u={self.FOLLOW_U}"
        response = await asyncio.to_thread(requests.get, follow_url, timeout=10)
        result = response.json()

        if result.get("msg") == "OK":
            await self.bot.send_msg(f"已关注 {user_name}", "#FFFF00")
        else:
            await self.bot.send_msg(f"关注失败: {result.get('msg', '未知错误')}", "#FF0000")

    async def handle_unfollow(self, sid: str):
        """取关用户"""
        user_info = await asyncio.to_thread(self._get_user_info, sid)
        if not user_info:
            await self.bot.send_msg(f"未找到用户: {sid}", "#FF0000")
            return

        user_id = user_info["userId"]
        user_name = user_info.get("userName") or user_info.get("UserName") or "未知"

        unfollow_url = f"https://t1.ss911.cn/User/FriendDo.ss?type=4&fid={user_id}&both=1&u={self.FOLLOW_U}"
        response = await asyncio.to_thread(requests.get, unfollow_url, timeout=10)
        result = response.json()

        if result.get("msg") == "OK":
            await self.bot.send_msg(f"已取关 {user_name}", "#FFFF00")
        else:
            await self.bot.send_msg(f"取关失败: {result.get('msg', '未知错误')}", "#FF0000")

    async def _send_long_message(self, msg: str, color: str, prefix: bool = False):
        """发送长消息（分段发送）"""
        if prefix:
            await self.bot.send_msg(msg, color)
        else:
            for line in msg.split("\n"):
                if not line.strip():
                    continue
                for i in range(0, len(line), 150):
                    await self.bot.send_msg(line[i:i + 150], color)
                    await asyncio.sleep(1.5)
