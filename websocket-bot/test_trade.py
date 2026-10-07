import unittest
import asyncio
import json
from datetime import datetime

from bot.handlers.trade import TradeHandler


class TradeFormattingTest(unittest.TestCase):
    def test_recent_trade_window_keeps_only_two_months(self):
        now = datetime(2026, 10, 7)
        goods = [
            {"addtime": "2026-09-15 19:16:53"},
            {"addtime": "2026-08-10 10:00:00"},
            {"addtime": "2026-01-01 10:00:00"},
        ]
        self.assertEqual(len(TradeHandler._recent_trade_goods(goods, now)), 2)

    def test_unknown_trade_date_is_not_discarded(self):
        self.assertEqual(
            TradeHandler._recent_trade_goods([{"addtime": ""}], datetime(2026, 10, 7)),
            [{"addtime": ""}],
        )

    def test_trend_summary_identifies_daily_average_prices(self):
        sent = []

        class Bot:
            async def send_msg(self, message, _color):
                sent.append(message)

        handler = object.__new__(TradeHandler)
        handler.bot = Bot()
        asyncio.run(handler._send_trend_summary("星星点点", [
            {"inttime": "2026-09-15", "price": 770000},
            {"inttime": "2026-09-14", "price": 65},
        ], 1))
        self.assertIn("日均价格", sent[0])
        self.assertIn("条记录", sent[0])
        self.assertIn("日均价", sent[0])
        self.assertNotIn("成交点", sent[0])

    def test_concurrent_trade_failures_are_scoped_to_each_request(self):
        class Bot:
            def _log(self, _message):
                pass

        class Response:
            def __init__(self, body):
                self.body = body

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def text(self):
                return self.body

        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, **_kwargs):
                self.calls.append(url)
                if "objid=bad" in url:
                    raise RuntimeError("network down")
                return Response(json.dumps({"goods": [{"addtime": "2026-10-07"}], "count": 1}))

        handler = object.__new__(TradeHandler)
        handler.bot = Bot()
        handler._cache = {}
        session = Session()

        async def run():
            return await asyncio.gather(
                handler._fetch_trade_page("ok", 1, session),
                handler._fetch_trade_page("bad", 1, session),
            )

        success, failure = asyncio.run(run())
        self.assertFalse(success[3])
        self.assertTrue(failure[3])
        self.assertEqual(len(session.calls), 4)


if __name__ == "__main__":
    unittest.main()
