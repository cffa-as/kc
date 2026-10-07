import unittest
from datetime import datetime, timedelta

from utils import filter_messages_by_time


class MessageTimeFilterTest(unittest.TestCase):
    def test_full_date_does_not_include_previous_day(self):
        now = datetime.now().replace(microsecond=0)
        messages = [
            {"timestamp": (now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")},
            {"timestamp": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")},
        ]
        self.assertEqual(filter_messages_by_time(messages, 5), messages[:1])


if __name__ == "__main__":
    unittest.main()
