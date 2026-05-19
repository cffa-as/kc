"""通用工具模块"""

import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, Callable


def get_project_path() -> str:
    """获取项目根目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json_file(file_path: str, default=None) -> dict:
    """加载JSON文件"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default or {}


def save_json_file(file_path: str, data: dict):
    """保存JSON文件"""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def filter_messages_by_time(messages: list, minutes: int, time_key: str = "timestamp") -> list:
    """按时间过滤消息（处理跨午夜情况）"""
    now = datetime.now()
    current_time_str = now.strftime("%H:%M:%S")
    cutoff_time_str = (now - timedelta(minutes=minutes)).strftime("%H:%M:%S")

    filtered = []
    for msg in messages:
        msg_time = msg.get(time_key, "")
        if not msg_time:
            continue
        if cutoff_time_str <= current_time_str:
            if cutoff_time_str <= msg_time <= current_time_str:
                filtered.append(msg)
        else:
            if msg_time >= cutoff_time_str or msg_time <= current_time_str:
                filtered.append(msg)
    return filtered


def parse_room_sync(msg: str) -> dict:
    """解析SO_Sync消息"""
    result = {}

    if "Player" in msg:
        player_blocks = re.findall(r'\[1,"?(\d+)"?,\{(.*?)\}\]', msg, re.DOTALL)
        players = []
        for user_id, block in player_blocks:
            name_m = re.search(r'"UserName"\s*:\s*"([^"]+)"', block)
            site_m = re.search(r'"RoomSite"\s*:\s*(\d+)', block)
            if name_m and site_m:
                players.append({
                    "UserId": user_id,
                    "UserName": name_m.group(1),
                    "RoomSite": int(site_m.group(1))
                })
        result["players"] = players
    else:
        try:
            data = json.loads(msg)
            for item in data.get("l", []):
                if len(item) >= 3 and item[0] == 1:
                    result[str(item[1])] = item[2]
        except Exception:
            pass

    n_match = re.search(r'"n":"([^"]+)"', msg)
    if n_match:
        result["n"] = n_match.group(1)

    return result


def split_message(text: str, max_len: int = 100) -> list:
    """分割长消息"""
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


class Logger:
    """日志记录器"""

    def __init__(self, log_file: str = None, filters: list = None):
        self.log_file = None
        self.log_path = log_file
        self.filters = set(filters or [])
        self._open(log_file)

    def _open(self, log_file: str):
        """打开日志文件"""
        if log_file:
            self.log_path = log_file
            self.log_file = open(log_file, "a", encoding="utf-8")

    def log(self, msg: str):
        """记录日志"""
        for f in self.filters:
            if f in msg:
                return

        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {msg}\n"
        print(log_line.strip())
        if self.log_file:
            self.log_file.write(log_line)
            self.log_file.flush()

    def close(self):
        """关闭日志文件"""
        if self.log_file:
            self.log_file.close()


class Censor:
    """敏感词过滤器"""

    def __init__(self, words_file: str = None):
        self.words = self._load_words(words_file)

    def _load_words(self, words_file: str = None) -> set:
        """加载敏感词"""
        if words_file is None:
            words_file = os.path.join(get_project_path(), "敏感词.json")
        try:
            data = load_json_file(words_file, {})
            return set(data.get("words", []))
        except Exception:
            return set()

    def censor(self, msg: str) -> str:
        """检查并处理敏感词"""
        for word in self.words:
            if word in msg:
                msg = msg.replace(word, ".".join(word))
        return msg


def extract_number(text: str, pattern: str = r'\d+') -> Optional[str]:
    """从文本中提取数字"""
    match = re.search(pattern, text)
    return match.group(1) if match else None
