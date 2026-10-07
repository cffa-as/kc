import gzip
import unittest

from bot.core import decode_server_message


class DecodeServerMessageTest(unittest.TestCase):
    def test_plain_text_is_unchanged(self):
        self.assertEqual(decode_server_message("RoomSay{}"), "RoomSay{}")

    def test_z_prefixed_gzip_frame_is_decoded(self):
        message = 'SO_Sync{"n":"Player3062","l":[]}'
        frame = b"Z\x01" + gzip.compress(message.encode("utf-8"), mtime=0)
        self.assertEqual(decode_server_message(frame), message)


if __name__ == "__main__":
    unittest.main()
