"""消息分发处理器"""

import asyncio
import re
import json
from typing import TYPE_CHECKING, Callable, Awaitable, Optional

if TYPE_CHECKING:
    from ..core import GameBot


class MessageDispatcher:
    """消息分发器 - 统一处理所有消息命令"""

    def __init__(self, bot: "GameBot"):
        self.bot = bot
        self._handlers: list[tuple[re.Pattern, Callable]] = []
        self._last_crack_room: Optional[str] = None
        self._register_handlers()

    def _register_handlers(self):
        """注册所有命令处理器"""
        # 菜单
        self.add_handler(r'菜单', self._handle_menu)

        # 排行榜
        self.add_handler(r'查(周|月)榜', self._handle_rank)
        self.add_handler(r'(总结喇叭|喇叭总结)', self._handle_summary)
        self.add_handler(r'(喇叭提问|提问喇叭)', self._handle_question)

        # 房间
        self.add_handler(r'^查房(\d+)', self._handle_room_query)
        self.add_handler(r'(总结房间|房间总结)\s*(\d+)', self._handle_room_summary)
        self.add_handler(r'^聊天记录(\d+)(?:@(\d+))?$', self._handle_chat_history)
        self.add_handler(r'^聊天记录$', lambda m: self.bot.handlers['room'].handle_chat_history(10))
        self.add_handler(r'^记录提问\s*(?:@(\d+))?\s*(.+)$', self._handle_chat_question)
        self.add_handler(r'^提问记录\s*(?:@(\d+))?\s*(.+)$', self._handle_chat_question)

        # 固定房间
        self.add_handler(r'^固定房间\s*(\d+)', self._handle_fixed_room)
        self.add_handler(r'取消固定', self._handle_cancel_fixed_room)

        # 去房间
        self.add_handler(r'^去\s*(\d+)', self._handle_go_room)

        # 跟随
        self.add_handler(r'^自动跟随\s*(\d+)', self._handle_auto_follow)
        self.add_handler(r'取消跟随', self._handle_cancel_follow)

        # 自动换位
        self.add_handler(r'开启自动换位', self._handle_auto_change_on)
        self.add_handler(r'关闭自动换位', self._handle_auto_change_off)

        # 明星提醒
        self.add_handler(r'开启明星提醒', self._handle_star_reminder_on)
        self.add_handler(r'关闭明星提醒', self._handle_star_reminder_off)

        # 跟随语
        self.add_handler(r'^跟随语\s*(.+)', self._handle_follow_message)

        # 破解
        self.add_handler(r'破解\s*(\d+)', self._handle_crack)

        # 权限管理
        self.add_handler(r'添加权限\s*(\d+)', self._handle_add_permission)
        self.add_handler(r'删除权限\s*(\d+)', self._handle_remove_permission)

        # 用户分析
        self.add_handler(r'^锐评动态\s*(\d+)', self._handle_roast)
        self.add_handler(r'^关注\s*(\d+)', self._handle_follow_user)
        self.add_handler(r'^取关\s*(\d+)', self._handle_unfollow_user)
        self.add_handler(r'^分析动态\s*(\d+)', self._handle_analysis)

        # AI聊天
        self.add_handler(r'^AI', self._handle_ai_chat)

        # 换位
        self.add_handler(r'^#上树', self._handle_gotree)
        self.add_handler(r'^#换位\s*(\d+)', self._handle_change_site)

    def add_handler(self, pattern: str, handler: Callable):
        """添加命令处理器"""
        self._handlers.append((re.compile(pattern), handler))

    async def dispatch(self, content: str, user_id: Optional[str] = None):
        """分发消息到对应处理器"""
        for pattern, handler in self._handlers:
            match = pattern.search(content)
            if match:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(match))
                    else:
                        handler(match)
                except Exception as e:
                    self.bot._log(f"处理命令失败: {e}")
                return True
        return False

    async def _handle_menu(self, match):
        """发送菜单"""
        await self.bot.send_msg("功能列表")
        menus = [
            "1.查周榜/查月榜+道具名(可选)",
            "2.总结喇叭N/喇叭提问N/总结房间N",
            "3.破解+房间号",
            "4.查房+房间号",
            "5.AI+问题",
            "6.分析/锐评动态+用户ID",
            "7.开启/关闭自动换位",
            "8.开启/关闭明星提醒",
            "9.聊天记录N条（可选@用户ID筛选）",
            "10.记录提问+问题（可选@用户ID）"
        ]
        for m in menus:
            await asyncio.sleep(1)
            await self.bot.send_msg(m)

    async def _handle_rank(self, match):
        """处理排行榜查询"""
        content = match.string
        await self.bot.handlers['rank'].handle_rank_query(content)

    async def _handle_summary(self, match):
        """处理喇叭总结"""
        await self.bot.handlers['ai'].handle_ai_summary(match.string)

    async def _handle_question(self, match):
        """处理喇叭提问"""
        await self.bot.handlers['ai'].handle_ai_question(match.string)

    async def _handle_room_query(self, match):
        """处理查房"""
        room_id = match.group(1)
        await self.bot.handlers['room'].handle_room_query(room_id)

    async def _handle_room_summary(self, match):
        """处理房间总结"""
        minutes = int(match.group(2))
        await self.bot.handlers['ai'].handle_room_summary(minutes)

    async def _handle_chat_history(self, match):
        """处理聊天记录（可选筛选用户）"""
        count = int(match.group(1))
        user_id = match.group(2)  # 可选
        await self.bot.handlers['ai'].handle_chat_history(count, user_id)

    async def _handle_chat_question(self, match):
        """处理聊天记录提问（可选筛选用户）"""
        user_id = match.group(1)  # 可选
        question = match.group(2).strip()
        await self.bot.handlers['ai'].handle_chat_question(question, user_id)

    async def _handle_fixed_room(self, match):
        """设置固定房间"""
        room_id = match.group(1)
        self.bot.set_fixed_room(room_id)
        await self.bot.send_msg(f"已设置固定房间: {room_id}")

    async def _handle_cancel_fixed_room(self, match):
        """取消固定房间"""
        self.bot.clear_fixed_room()
        await self.bot.send_msg("已取消固定房间")

    async def _handle_auto_follow(self, match):
        """设置自动跟随"""
        sid = match.group(1)
        await self.bot.set_auto_follow(sid)
        await self.bot.send_msg(f"已设置自动跟随: {sid}")

    async def _handle_cancel_follow(self, match):
        """取消跟随"""
        self.bot.clear_auto_follow()
        self.bot._current_followed_room = ""
        await self.bot.send_msg("已取消自动跟随")

    async def _handle_auto_change_on(self, match):
        """开启自动换位"""
        await self.bot.toggle_auto_change_site(True)
        await self.bot.send_msg(f"自动换位: {'开启' if self.bot._auto_change_site else '关闭'}")

    async def _handle_auto_change_off(self, match):
        """关闭自动换位"""
        await self.bot.toggle_auto_change_site(False)
        await self.bot.send_msg(f"自动换位: {'开启' if self.bot._auto_change_site else '关闭'}")

    async def _handle_star_reminder_on(self, match):
        """开启明星提醒"""
        await self.bot.toggle_star_reminder(True)
        await self.bot.send_msg(f"明星提醒: {'开启' if self.bot._star_reminder else '关闭'}")

    async def _handle_star_reminder_off(self, match):
        """关闭明星提醒"""
        await self.bot.toggle_star_reminder(False)
        await self.bot.send_msg(f"明星提醒: {'开启' if self.bot._star_reminder else '关闭'}")

    async def _handle_follow_message(self, match):
        """设置跟随语"""
        user_id = getattr(self.bot, '_current_user_id', None)
        if user_id and user_id in self.bot._owners:
            msg_content = match.group(1).strip()
            if msg_content:
                self.bot.set_follow_message(msg_content)
                await self.bot.send_msg(f"已设置跟随语: {msg_content}")
            else:
                current_msg = self.bot.get_follow_message()
                await self.bot.send_msg(f"当前跟随语: {current_msg if current_msg else '未设置'}")
        else:
            await self.bot.send_msg("只有主人才能设置跟随语")

    async def _handle_crack(self, match):
        """处理破解"""
        room_id = match.group(1)
        self._last_crack_room = room_id
        await self.bot.handlers['crack'].handle_crack(room_id)

    async def _handle_add_permission(self, match):
        """添加权限"""
        user_id = getattr(self.bot, '_current_user_id', None)
        if user_id and user_id in self.bot._owners:
            target_user = match.group(1)
            self.bot.add_allowed_user(target_user)
            await self.bot.send_msg("添加成功")

    async def _handle_remove_permission(self, match):
        """删除权限"""
        user_id = getattr(self.bot, '_current_user_id', None)
        if user_id and user_id in self.bot._owners:
            target_user = match.group(1)
            self.bot.remove_allowed_user(target_user)
            await self.bot.send_msg("删除成功")

    async def _handle_follow_user(self, match):
        """关注用户"""
        sid = match.group(1)
        await self.bot.handlers['user'].handle_follow(sid)

    async def _handle_unfollow_user(self, match):
        """取关用户"""
        sid = match.group(1)
        await self.bot.handlers['user'].handle_unfollow(sid)

    async def _handle_roast(self, match):
        """锐评动态"""
        sid = match.group(1)
        await self.bot.handlers['user'].handle_roast(sid)

    async def _handle_analysis(self, match):
        """用户分析"""
        sid = match.group(1)
        await self.bot.handlers['user'].handle_analysis(sid)

    async def _handle_ai_chat(self, match):
        """AI聊天"""
        await self.bot.handlers['ai'].handle_ai_chat(match.string)

    async def _handle_gotree(self, match):
        """上树"""
        await self.bot.handlers['room'].handle_change_site("-1", send_follow_msg=False)

    async def _handle_change_site(self, match):
        """换位"""
        site = int(match.group(1))
        if 1 <= site <= 20:
            await self.bot.handlers['room'].handle_change_site(str(site), send_follow_msg=False)
        else:
            await self.bot.send_msg("换位只支持1-20")

    async def _handle_go_room(self, match):
        """去指定房间"""
        room_id = match.group(1)
        await self.bot.send({"RoomId": room_id, "Password": "", "c": "JoinRoom"})
        self.bot._log(f"去房间: {room_id}")
