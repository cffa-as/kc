"""消息分发处理器"""

import asyncio
import re
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ..core import GameBot


class MessageDispatcher:
    """消息分发器"""

    def __init__(self, bot: "GameBot"):
        self.bot = bot
        self._handlers: list[tuple[re.Pattern, Callable]] = []
        self._last_crack_room: Optional[str] = None
        self._current_user_id: Optional[str] = None
        self._register_handlers()

    def _register_handlers(self):
        self.add_handler(r'菜单', self._handle_menu)
        self.add_handler(r'查(周|月|年)榜', self._handle_rank)
        self.add_handler(r'(总结喇叭|喇叭总结)', self._handle_summary)
        self.add_handler(r'(喇叭提问|提问喇叭)', self._handle_question)
        self.add_handler(r'^查房(\d+)', self._handle_room_query)
        self.add_handler(r'(总结房间|房间总结)\s*(\d+)', self._handle_room_summary)
        self.add_handler(r'^聊天记录(\d+)(?:@(\d+))?$', self._handle_chat_history)
        self.add_handler(r'^聊天记录$', lambda m: self.bot.handlers['ai'].handle_chat_history(10))
        self.add_handler(r'^记录提问\s*(?:@(\d+))?\s*(.+)$', self._handle_chat_question)
        self.add_handler(r'^提问记录\s*(?:@(\d+))?\s*(.+)$', self._handle_chat_question)
        self.add_handler(r'^固定房间\s*(\d+)', self._handle_fixed_room)
        self.add_handler(r'取消固定', self._handle_cancel_fixed_room)
        self.add_handler(r'^去\s*(\d+)', self._handle_go_room)
        self.add_handler(r'开启明星提醒', self._handle_star_reminder)
        self.add_handler(r'关闭明星提醒', self._handle_star_reminder)
        self.add_handler(r'破解\s*(\d+)', self._handle_crack)
        self.add_handler(r'添加权限\s*(\d+)', self._handle_add_permission)
        self.add_handler(r'删除权限\s*(\d+)', self._handle_remove_permission)
        self.add_handler(r'^锐评动态\s*(\d+)', self._handle_roast)
        self.add_handler(r'^关注\s*(\d+)', self._handle_follow_user)
        self.add_handler(r'^取关\s*(\d+)', self._handle_unfollow_user)
        self.add_handler(r'^分析动态\s*(\d+)', self._handle_analysis)
        self.add_handler(r'^AI', self._handle_ai_chat)
        self.add_handler(r'^#上树', self._handle_gotree)
        self.add_handler(r'^#换位\s*(\d+)', self._handle_change_site)

    def add_handler(self, pattern: str, handler: Callable):
        self._handlers.append((re.compile(pattern), handler))

    async def dispatch(self, content: str, user_id: Optional[str] = None):
        self._current_user_id = user_id
        for pattern, handler in self._handlers:
            if match := pattern.search(content):
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
        await self.bot.send_msg("功能列表")
        for m in ["1.查周榜/查周榜2/查月榜/查月榜2+道具名(可选)",
                  "2.总结喇叭N/喇叭提问N/总结房间N",
                  "3.破解+房间号", "4.查房+房间号", "5.AI+问题",
                  "6.分析/锐评动态+用户ID", "7.开启/关闭明星提醒",
                  "8.聊天记录N条（可选@用户ID筛选）", "9.记录提问+问题（可选@用户ID）"]:
            await asyncio.sleep(1)
            await self.bot.send_msg(m)

    async def _handle_rank(self, match):
        await self.bot.handlers['rank'].handle_rank_query(match.string)

    async def _handle_summary(self, match):
        await self.bot.handlers['ai'].handle_ai_summary(match.string)

    async def _handle_question(self, match):
        await self.bot.handlers['ai'].handle_ai_question(match.string)

    async def _handle_room_query(self, match):
        await self.bot.handlers['room'].handle_room_query(match.group(1))

    async def _handle_room_summary(self, match):
        await self.bot.handlers['ai'].handle_room_summary(int(match.group(2)))

    async def _handle_chat_history(self, match):
        await self.bot.handlers['ai'].handle_chat_history(int(match.group(1)), match.group(2))

    async def _handle_chat_question(self, match):
        await self.bot.handlers['ai'].handle_chat_question(match.group(2).strip(), match.group(1))

    async def _handle_fixed_room(self, match):
        self.bot.set_fixed_room(match.group(1))
        await self.bot.send_msg(f"已设置固定房间: {match.group(1)}")

    async def _handle_cancel_fixed_room(self, match):
        self.bot.clear_fixed_room()
        await self.bot.send_msg("已取消固定房间")

    async def _handle_star_reminder(self, match):
        enable = "开启" in match.string
        await self.bot.toggle_star_reminder(enable)
        await self.bot.send_msg(f"明星提醒: {'开启' if enable else '关闭'}")

    async def _handle_crack(self, match):
        self._last_crack_room = match.group(1)
        await self.bot.handlers['crack'].handle_crack(match.group(1))

    async def _handle_add_permission(self, match):
        if self._current_user_id and self._current_user_id in self.bot._owners:
            self.bot.add_allowed_user(match.group(1))
            await self.bot.send_msg("添加成功")

    async def _handle_remove_permission(self, match):
        if self._current_user_id and self._current_user_id in self.bot._owners:
            self.bot.remove_allowed_user(match.group(1))
            await self.bot.send_msg("删除成功")

    async def _handle_follow_user(self, match):
        await self.bot.handlers['user'].handle_follow(match.group(1))

    async def _handle_unfollow_user(self, match):
        await self.bot.handlers['user'].handle_unfollow(match.group(1))

    async def _handle_roast(self, match):
        await self.bot.handlers['user'].handle_roast(match.group(1))

    async def _handle_analysis(self, match):
        await self.bot.handlers['user'].handle_analysis(match.group(1))

    async def _handle_ai_chat(self, match):
        await self.bot.handlers['ai'].handle_ai_chat(match.string)

    async def _handle_gotree(self, match):
        await self.bot.handlers['room'].handle_change_site("-1")

    async def _handle_change_site(self, match):
        site = int(match.group(1))
        if 1 <= site <= 20:
            await self.bot.handlers['room'].handle_change_site(str(site))
        else:
            await self.bot.send_msg("换位只支持1-20")

    async def _handle_go_room(self, match):
        await self.bot.send({"RoomId": match.group(1), "Password": "", "c": "JoinRoom"})
