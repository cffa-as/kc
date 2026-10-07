import asyncio
import contextvars
import unittest

from bot.core import GameBot, is_wecom_progress_message
from wecom import normalize_wecom_command, split_wecom_reply


class WeComTest(unittest.TestCase):
    def test_group_mention_is_removed(self):
        self.assertEqual(normalize_wecom_command("@查询机器人 查周榜玫瑰", "group"), "查周榜玫瑰")
        self.assertEqual(normalize_wecom_command("查周榜", "single"), "查周榜")

    def test_replies_are_combined_and_split(self):
        self.assertEqual(split_wecom_reply(["榜单", "1. 玩家"], 20), ["榜单  \n1. 玩家"])
        self.assertEqual(split_wecom_reply(["标题\n第一行\n第二行"], 30), ["标题  \n第一行  \n第二行"])
        self.assertEqual(
            split_wecom_reply(["时间:2026-10-07 | 总价:100｜有效期:3天"], 100),
            ["时间:2026-10-07  \n总价:100  \n有效期:3天"],
        )
        self.assertEqual(split_wecom_reply(["12345", "67890"], 7), ["12345", "67890"])

    def test_existing_dispatcher_replies_return_to_same_chat(self):
        sent = []
        bot = object.__new__(GameBot)
        bot._wecom_replies = contextvars.ContextVar("test_wecom_replies", default=None)
        bot._wecom_allowed_users = set()
        bot._log = lambda _message: None

        class Bridge:
            async def send_markdown(self, chat_id, content):
                sent.append((chat_id, content))

        class Dispatcher:
            async def dispatch(self, content, user_id, wait=False):
                self.assertions = (content, user_id, wait)
                await bot.send_msg("周榜")
                await bot.send_msg("1. 玩家")
                return True

        dispatcher = Dispatcher()
        bot._wecom_bridge = Bridge()
        bot.handlers = {"dispatcher": dispatcher}
        asyncio.run(bot._handle_wecom_message({
            "chatId": "group-1",
            "chatType": "group",
            "userId": "member-1",
            "content": "@查询机器人 查周榜",
        }))
        self.assertEqual(dispatcher.assertions, ("查周榜", "member-1", True))
        self.assertEqual(sent, [("group-1", "周榜  \n1. 玩家")])

    def test_message_delay_is_skipped_while_collecting_wecom_replies(self):
        bot = object.__new__(GameBot)
        bot._wecom_replies = contextvars.ContextVar("test_message_delay", default=None)
        token = bot._wecom_replies.set([])
        try:
            asyncio.run(bot.message_delay(60))
        finally:
            bot._wecom_replies.reset(token)

    def test_transient_progress_messages_are_hidden_from_wecom(self):
        self.assertTrue(is_wecom_progress_message("正在查询周榜..."))
        self.assertTrue(is_wecom_progress_message("开始破解房间 3062..."))
        self.assertTrue(is_wecom_progress_message("名称「玫瑰」匹配 2 个物品，查询颜色..."))
        self.assertTrue(is_wecom_progress_message("查询出 3 个颜色，开始聚合查询..."))
        self.assertFalse(is_wecom_progress_message("【本周榜道具榜】"))
        self.assertFalse(is_wecom_progress_message("暂无周榜数据"))


if __name__ == "__main__":
    unittest.main()
