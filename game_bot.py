#!/usr/bin/env python3
"""kc游戏机器人"""

import asyncio
import json
import os
import re
import requests
import time
from datetime import datetime, timedelta

try:
    import websockets
except ImportError:
    print("请先安装: pip install websockets")
    exit(1)


# AI配置
AI_API_KEY = "sk-cc4f4275928f4e0e9b388f0362507c47"
AI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
AI_MODEL_NAME = "qwen-max"


class AISummarizer:
    """总结工具"""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

    def summarize(self, messages: list, minutes: int = 5) -> str:
        """调用通义千问API总结喇叭消息"""
        if not messages:
            return "最近{}分钟暂无喇叭消息".format(minutes)

        prompt = self._build_prompt(messages)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个游戏喇叭消息总结助手。请只根据提供的喇叭消息内容进行总结，不要猜测或编造任何信息。重要提示：房间号是4位数（如1001、2008、3005等），不是13172这样的数字。如果消息中没有明确提到房间号，不要猜测。回复格式要求：每个要点用分号+换行分隔，不要使用JSON格式，不要使用markdown格式。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"总结失败: {e}"

    def _build_prompt(self, messages: list) -> str:
        """构建提示词"""
        msg_texts = []
        for msg in messages:
            username = msg.get("userName", "未知玩家")
            content = msg.get("msg", "")
            msg_texts.append(f"{username}：{content}")

        messages_str = "\n".join(msg_texts)
        return f"请总结以下游戏喇叭消息（每个消息格式为：玩家名：消息内容）：\n{messages_str}\n\n请用简洁的中文总结这些喇叭的主要内容。"

    def answer_question(self, messages: list, question: str, minutes: int = 60) -> str:
        """根据喇叭消息回答问题"""
        if not messages:
            return f"最近{minutes}分钟暂无喇叭消息，无法回答"

        msg_texts = []
        for msg in messages:
            username = msg.get("userName", "未知玩家")
            content = msg.get("msg", "")
            msg_texts.append(f"{username}：{content}")

        messages_str = "\n".join(msg_texts)

        prompt = f"以下是最近{minutes}分钟的游戏喇叭消息：\n{messages_str}\n\n请根据以上喇叭消息回答问题：{question}\n\n要求：1. 只根据消息内容回答，不要猜测 2. 如果没有相关信息，说明没有 3. 引用消息时保留原内容 4. 用分号+换行分隔多个信息"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个游戏喇叭助手。请根据提供的喇叭消息回答玩家的问题，只回答消息中确实存在的信息，不要猜测或编造。房间号是4位数（如1001、2008等）。重要：1. 不要使用markdown格式 2. 用分号+换行分隔多个信息 3. 引用消息时保留玩家原话"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"查询失败: {e}"

    def summarize_room_messages(self, messages: list, minutes: int = 5) -> str:
        """调用通义千问API总结房间消息"""
        if not messages:
            return f"最近{minutes}分钟暂无消息"

        msg_texts = []
        for msg in messages:
            site = msg.get("site", "?")
            username = msg.get("userName", "未知玩家")
            content = msg.get("msg", "")
            msg_texts.append(f"{site}{username}：{content}")

        messages_str = "\n".join(msg_texts)
        prompt = f"请总结以下房间消息（每个消息格式为：玩家名：消息内容）：\n{messages_str}\n\n请用简洁的中文总结这些消息的主要内容。"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个游戏房间消息总结助手。请只根据提供的内容进行总结，不要猜测或编造。回复格式要求：每个要点用分号+换行分隔，不要使用JSON格式，不要使用markdown格式。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"总结失败: {e}"

    def direct_answer(self, question: str) -> str:
        """直接回答问题，不需要喇叭消息"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个友好的助手。请直接回答问题，回答简洁明了。不要使用markdown格式，用分号+换行分隔多个信息。"
                },
                {
                    "role": "user",
                    "content": question
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"调用AI失败: {e}"


class RankQuery:
    """排行榜查询工具"""

    def __init__(self):
        self.base_url = "https://t1.ss911.cn/Rank/GetToolRank.ss"
        self.tool_url = "https://t1.ss911.cn/Rank/GetToolRank.ss"
        self.cookie = "JSESSIONID=F9257055C5772AB3E8712872FF04674F; Hm_lvt_8db5877631f6b3e1e50b3a82695c5484=1777547687,1777731807,1778506341,1778936394; HMACCOUNT=410244466E960FFE; UserId=126521216; UserName=14705896759; UserPwd=3115e599ad5a97c0; uservalues=ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D; LastLogin=2026-05-16~21:00:05; yzmCode=wcvqGqJhW68Z8trn%2B184%2BBOWb59LRIeZ; Hm_lpvt_8db5877631f6b3e1e50b3a82695c5484"
        self.headers = {"Cookie": self.cookie}
        self.tool_map = {}  # 道具名 -> objid
        self.tool_map_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_map.json")
        self.tool_data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "道具完整数据.json")
        self.tool_data = {}  # 道具完整数据
        self._load_tool_map()
        self._load_tool_data()

    def _load_tool_map(self):
        """加载道具映射表"""
        if os.path.exists(self.tool_map_file):
            try:
                with open(self.tool_map_file, "r", encoding="utf-8") as f:
                    self.tool_map = json.load(f)
            except:
                self.tool_map = {}

    def _load_tool_data(self):
        """加载道具完整数据"""
        if os.path.exists(self.tool_data_file):
            try:
                with open(self.tool_data_file, "r", encoding="utf-8") as f:
                    self.tool_data = json.load(f)
                print(f"[DEBUG] 加载道具数据成功，共 {len(self.tool_data)} 个道具")
            except Exception as e:
                print(f"[ERROR] 加载道具数据失败: {e}")
                self.tool_data = {}
        else:
            print(f"[ERROR] 道具数据文件不存在: {self.tool_data_file}")

    def _save_tool_data(self):
        """保存道具完整数据"""
        with open(self.tool_data_file, "w", encoding="utf-8") as f:
            json.dump(self.tool_data, f, ensure_ascii=False, indent=2)

    def get_tool_price(self, name: str) -> float:
        """获取道具守护值"""
        if name in self.tool_data:
            return self.tool_data[name].get("price", 0.0)
        # 模糊匹配
        for tool_name, data in self.tool_data.items():
            if name in tool_name or tool_name in name:
                print(f"[DEBUG] 模糊匹配: {name} -> {tool_name}, price: {data.get('price', 0.0)}")
                return data.get("price", 0.0)
        print(f"[DEBUG] 未找到道具价格: {name}, 已有道具: {list(self.tool_data.keys())[:10]}")
        return 0.0

    def update_tool_objid(self, name: str, objid: str):
        """更新道具objid到道具完整数据.json"""
        if name in self.tool_data and self.tool_data[name].get("objid", "0") == "0":
            self.tool_data[name]["objid"] = objid
            self._save_tool_data()
            print(f"[更新] {name} objid -> {objid}")

    def fetch_tool_list(self, rank_type: str = "week"):
        """获取道具列表"""
        h_value = "0" if rank_type == "week" else "2"
        params = {
            "h": h_value,
            "g": "0",
            "n": "3",
            "p": "1",
            "u": "ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D"
        }
        try:
            resp = requests.get(self.tool_url, params=params, headers=self.headers, timeout=10)
            data = resp.json()
            if "rankList" in data:
                for item in data["rankList"]:
                    objname = item.get("objname", "")
                    objid = str(item.get("objid", ""))
                    if objname and objid:
                        self.tool_map[objname] = objid
                        # 更新道具完整数据中的objid
                        if objname in self.tool_data:
                            self.update_tool_objid(objname, objid)
                # 保存tool_map
                with open(self.tool_map_file, "w", encoding="utf-8") as f:
                    json.dump(self.tool_map, f, ensure_ascii=False, indent=2)
                return True
        except Exception as e:
            print(f"获取道具列表失败: {e}")
        return False

    def get_tool_id(self, name: str) -> str:
        """获取道具ID"""
        # 精确匹配
        if name in self.tool_map:
            return self.tool_map[name]
        # 模糊匹配
        for tool_name, tool_id in self.tool_map.items():
            if name in tool_name or tool_name in name:
                return tool_id
        return None

    def fetch_all_tools(self, rank_type: str = "week"):
        """获取所有道具列表（不带toolid参数）"""
        h_value = "0" if rank_type == "week" else "2"
        params = {
            "h": h_value,
            "g": "0",
            "n": "3",
            "p": "1",
            "u": "ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D"
        }
        try:
            resp = requests.get(self.tool_url, params=params, headers=self.headers, timeout=10)
            data = resp.json()
            tools = []
            if "rankList" in data:
                for item in data["rankList"]:
                    objname = item.get("objname", "")
                    objid = str(item.get("objid", ""))
                    if objname and objid:
                        tools.append({"name": objname, "id": objid})
                        self.tool_map[objname] = objid
                        # 更新道具完整数据中的objid
                        if objname in self.tool_data:
                            self.update_tool_objid(objname, objid)
                # 保存tool_map
                with open(self.tool_map_file, "w", encoding="utf-8") as f:
                    json.dump(self.tool_map, f, ensure_ascii=False, indent=2)
            return tools
        except Exception as e:
            print(f"获取道具列表失败: {e}")
        return []

    def query_player_tools(self, tool_id: str, tool_name: str, rank_type: str = "week") -> list:
        """查询指定道具的玩家排行榜

        Args:
            tool_id: 道具ID
            tool_name: 道具名
            rank_type: "week" 周榜, "month" 月榜

        Returns:
            排行榜结果列表
        """
        # h=0 周榜, h=2 月榜
        h_value = "0" if rank_type == "week" else "2"

        params = {
            "toolid": tool_id,
            "h": h_value,
            "g": "0",
            "n": "3",
            "p": "1",
            "u": "ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D"
        }
        try:
            resp = requests.get(self.tool_url, params=params, headers=self.headers, timeout=10)
            data = resp.json()
            results = []
            if "rankList" in data:
                for item in data["rankList"]:
                    results.append({
                        "userName": item.get("userName", ""),
                        "num": item.get("num", 0)
                    })
            return results
        except Exception as e:
            print(f"查询排行榜失败: {e}")
        return []

    def query_all_tools_rank(self, rank_type: str = "week") -> list:
        """查询所有道具的排行榜整合

        Args:
            rank_type: "week" 周榜, "month" 月榜

        Returns:
            整合后的排行榜列表 [(排名, 玩家名, 道具名, 数量, 总守护值), ...]
            每个道具只记录持有数量最多的那个玩家
        """
        # 先获取所有道具
        tools = self.fetch_all_tools(rank_type)
        if not tools:
            return []

        # 每个道具记录持有数量最多的玩家
        tool_best_player = {}  # {道具名: (玩家名, 数量, 单价)}

        for tool in tools:
            tool_name = tool["name"]
            tool_id = tool["id"]
            price = self.get_tool_price(tool_name)

            # 获取该道具的玩家排行榜
            players = self.query_player_tools(tool_id, tool_name, rank_type)

            # 找出持有该道具数量最多的玩家
            for player in players:
                username = player["userName"]
                num = player["num"]
                if tool_name not in tool_best_player or num > tool_best_player[tool_name][1]:
                    tool_best_player[tool_name] = (username, num, price)

        # 整合结果
        results = []
        for tool_name, (username, num, price) in tool_best_player.items():
            total_price = num * price
            results.append((username, tool_name, num, total_price))

        # 按总守护值排序
        results.sort(key=lambda x: x[3], reverse=True)

        # 添加排名
        ranked_results = []
        for i, (username, tool_name, num, total_price) in enumerate(results, 1):
            ranked_results.append((i, username, tool_name, num, total_price))

        return ranked_results

    def query_rank(self, tool_name: str, rank_type: str = "week") -> tuple:
        """查询道具排行榜

        Args:
            tool_name: 道具名
            rank_type: "week" 周榜, "month" 月榜

        Returns:
            (results, price): 排行榜结果列表和守护值
        """
        tool_id = self.get_tool_id(tool_name)
        if not tool_id:
            # 先获取道具列表
            self.fetch_tool_list(rank_type)
            tool_id = self.get_tool_id(tool_name)
            if not tool_id:
                return None, 0.0  # 找不到道具

        # 获取守护值
        price = self.get_tool_price(tool_name)

        # 更新道具objid（如果为0）
        self.update_tool_objid(tool_name, tool_id)

        # h=0 周榜, h=2 月榜
        h_value = "0" if rank_type == "week" else "2"

        params = {
            "toolid": tool_id,
            "h": h_value,
            "g": "0",
            "n": "3",
            "p": "1",
            "u": "ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D"
        }
        try:
            resp = requests.get(self.tool_url, params=params, headers=self.headers, timeout=10)
            data = resp.json()
            results = []
            if "rankList" in data:
                for item in data["rankList"]:
                    results.append({
                        "userName": item.get("userName", ""),
                        "num": item.get("num", 0)
                    })
            return results, price
        except Exception as e:
            print(f"查询排行榜失败: {e}")
        return [], price


class GameBot:
    """游戏机器人"""

    def __init__(self, url: str, origin: str = "https://t1.ss911.cn"):
        self.url = url
        self.origin = origin
        self.ws = None
        self.running = False
        self.log_file = None
        self.rank_query = RankQuery()
        self.ai_summarizer = AISummarizer(AI_API_KEY, AI_BASE_URL, AI_MODEL_NAME)
        self.sensitive_words = self._load_sensitive_words()
        self._room_query_pending = None
        self._login_token = ""
        self._login_device = ""
        self._login_p = ""
        self._bot_name = ""  # 机器人名字
        self._last_summary_time = 0  # 上次总结时间，防止重复
        self._room_cracking = False  # 是否正在破解房间
        self._crack_pending = None  # 破解状态
        self._last_heartbeat = time.time()  # 上次心跳时间
        self._allowed_users = set(self._load_config().get("allowed_users", []))  # 权限用户列表
        self._owners = set(self._load_config().get("owners", []))  # 主人列表
        self._auto_follow_sid = self._load_config().get("auto_follow_sid", "")  # 自动跟随的sid
        self._auto_follow_user_id = self._load_config().get("auto_follow_user_id", "")  # 跟随目标的userId
        self._current_followed_room = ""  # 当前跟随的房间号
        self._auto_follow_task = None  # 自动跟随定时任务
        self._follow_message = self._load_config().get("follow_message", "")  # 跟随语
        self._log_filters = set(self._load_config().get("log_filters", []))  # 日志过滤器
        self._auto_change_site = self._load_config().get("auto_change_site", False)  # 自动换位开关
        self._auto_change_site_task = None  # 自动换位任务
        self._auto_change_site_last_players = []  # 上次的玩家列表
        self._last_followed_site = 0  # 上次跟随的位置
        self._my_user_id = ""  # 机器人自己的userId
        self._star_reminder = self._load_config().get("star_reminder", False)  # 明星提醒开关
        self._star_reminder_task = None  # 明星提醒定时任务
        self._star_reminder_sent_today = set()  # 今天已发送的提醒时间点 (hour, minute)
        self._servers = []  # 服务器列表
        self._current_server_index = 0  # 当前服务器索引
        self._join_fail_count = 0  # 进房失败计数
        self._query_fail_count = 0  # 查房失败计数
        self._player_query_handlers = {}  # {room_id: handler} 用于当前连接查房回调

    def _load_sensitive_words(self) -> set:
        """加载敏感词"""
        sensitive_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "敏感词.json")
        try:
            with open(sensitive_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("words", []))
        except Exception as e:
            print(f"加载敏感词失败: {e}")
            return set()

    def _load_config(self) -> dict:
        """加载配置文件"""
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, config: dict):
        """保存配置文件"""
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log(f"保存配置失败: {e}")

    def get_fixed_room(self) -> str:
        """获取固定房间号"""
        config = self._load_config()
        return config.get("fixed_room", "")

    def set_fixed_room(self, room_id: str):
        """设置固定房间号"""
        config = self._load_config()
        config["fixed_room"] = room_id
        self._save_config(config)
        self._log(f"已设置固定房间: {room_id}")

    def clear_fixed_room(self):
        """清除固定房间号"""
        config = self._load_config()
        if "fixed_room" in config:
            del config["fixed_room"]
            self._save_config(config)
            self._log("已清除固定房间")

    def add_allowed_user(self, user_id: str):
        """添加权限用户"""
        config = self._load_config()
        allowed = set(config.get("allowed_users", []))
        allowed.add(user_id)
        config["allowed_users"] = list(allowed)
        self._save_config(config)
        self._allowed_users = allowed
        self._log(f"已添加权限用户: {user_id}")

    def remove_allowed_user(self, user_id: str):
        """删除权限用户"""
        config = self._load_config()
        allowed = set(config.get("allowed_users", []))
        if user_id in allowed:
            allowed.remove(user_id)
            config["allowed_users"] = list(allowed)
            self._save_config(config)
            self._allowed_users = allowed
            self._log(f"已删除权限用户: {user_id}")
        else:
            self._log(f"用户 {user_id} 不在权限列表中")

    def is_allowed_user(self, user_id: str) -> bool:
        """检查用户是否有权限"""
        return str(user_id) in self._allowed_users or str(user_id) in [str(u) for u in self._allowed_users]

    async def set_auto_follow(self, sid: str):
        """设置自动跟随（设置时同步获取userId）"""
        # 先获取 userId
        user_id = await self.get_user_id_by_sid(sid)
        
        config = self._load_config()
        config["auto_follow_sid"] = sid
        config["auto_follow_user_id"] = user_id or ""
        self._save_config(config)
        self._auto_follow_sid = sid
        self._auto_follow_user_id = user_id or ""
        self._log(f"已设置自动跟随: sid={sid}, user_id={user_id or '获取失败'}")
        
        # 设置后立即重启跟随
        await self._restart_auto_follow()

    def clear_auto_follow(self):
        """清除自动跟随"""
        config = self._load_config()
        if "auto_follow_sid" in config:
            del config["auto_follow_sid"]
        if "auto_follow_user_id" in config:
            del config["auto_follow_user_id"]
        self._save_config(config)
        self._auto_follow_sid = ""
        self._auto_follow_user_id = ""
        self._log("已取消自动跟随")
        # 停止自动换位任务
        if self._auto_change_site_task:
            self._auto_change_site_task.cancel()
            self._auto_change_site_task = None
        self._last_followed_site = 0

    def get_auto_follow_sid(self) -> str:
        """获取自动跟随的sid"""
        return self._auto_follow_sid

    def get_auto_follow_user_id(self) -> str:
        """获取自动跟随的userId"""
        return self._auto_follow_user_id

    def set_follow_message(self, message: str):
        """设置跟随语"""
        config = self._load_config()
        config["follow_message"] = message
        self._save_config(config)
        self._follow_message = message
        self._log(f"已设置跟随语: {message}")

    def get_follow_message(self) -> str:
        """获取跟随语"""
        return self._follow_message

    async def get_user_id_by_sid(self, sid: str) -> str:
        """根据sid获取用户的userId"""
        u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"
        url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={u}"
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            data = response.json()
            if data.get("msg") == "OK" and data.get("data"):
                return data["data"][0].get("userId", "")
        except Exception as e:
            self._log(f"获取用户ID失败: {e}")
        return ""

    def _censor_message(self, msg: str) -> str:
        """检查并处理敏感词"""
        for word in self.sensitive_words:
            if word in msg:
                # 用 . 分隔每个字符
                censored = ".".join(word)
                msg = msg.replace(word, censored)
        return msg

    def _open_log(self):
        """打开日志文件"""
        log_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(log_dir, "bot.log")
        self.log_path = log_path  # 确保路径一致
        self.log_file = open(log_path, "a", encoding="utf-8")

    def _log(self, msg: str):
        """记录日志（过滤关键词可配置）"""
        # 检查是否需要过滤
        for f in self._log_filters:
            if f in msg:
                return  # 被过滤，不记录
        
        timestamp = self._t()
        log_line = f"[{timestamp}] {msg}\n"
        print(log_line.strip())
        if self.log_file:
            self.log_file.write(log_line)
            self.log_file.flush()

    async def toggle_auto_change_site(self, enable: bool):
        """开启/关闭自动换位"""
        self._auto_change_site = enable
        config = self._load_config()
        config["auto_change_site"] = enable
        self._save_config(config)
        self._log(f"自动换位: {'开启' if enable else '关闭'}")
        
        if enable and self._auto_follow_sid:
            await self._start_auto_change_site()
        else:
            await self._stop_auto_change_site()

    async def toggle_star_reminder(self, enable: bool):
        """开启/关闭明星提醒"""
        self._star_reminder = enable
        config = self._load_config()
        config["star_reminder"] = enable
        self._save_config(config)
        self._log(f"明星提醒: {'开启' if enable else '关闭'}")
        
        if enable:
            await self._start_star_reminder()
        else:
            await self._stop_star_reminder()

    async def _start_star_reminder(self):
        """启动明星提醒定时任务"""
        if self._star_reminder_task:
            self._star_reminder_task.cancel()
        self._star_reminder_task = asyncio.create_task(self._star_reminder_loop())

    async def _stop_star_reminder(self):
        """停止明星提醒定时任务"""
        if self._star_reminder_task:
            self._star_reminder_task.cancel()
            self._star_reminder_task = None

    async def _star_reminder_loop(self):
        """明星提醒循环：每秒检查是否需要发送提醒
        在每天的 9:02/03/04, 10:02/03/04, ..., 23:02/03/04 发送提醒
        """
        last_date = None
        
        while self.running and self._star_reminder:
            now = datetime.now()
            today = now.date()
            
            # 新的一天，重置已发送记录
            if last_date != today:
                self._star_reminder_sent_today = set()
                last_date = today
            
            hour = now.hour
            minute = now.minute
            second = now.second
            
            # 只在 9-23 点之间检查
            if 9 <= hour <= 23 and second <= 2:
                key = (hour, minute)
                if key not in self._star_reminder_sent_today:
                    if minute == 2:
                        await self.send_msg("明星还有3分钟", "#FF69B4")
                        self._star_reminder_sent_today.add(key)
                        self._log(f"发送明星3分钟提醒: {hour}:03")
                    elif minute == 3:
                        await self.send_msg("明星还有2分钟", "#FF69B4")
                        self._star_reminder_sent_today.add(key)
                        self._log(f"发送明星2分钟提醒: {hour}:04")
                    elif minute == 4:
                        await self.send_msg("明星还有1分钟", "#FF69B4")
                        self._star_reminder_sent_today.add(key)
                        self._log(f"发送明星1分钟提醒: {hour}:05")
            
            await asyncio.sleep(1)

    async def connect(self) -> bool:
        """连接服务器"""
        try:
            self.ws = await websockets.connect(
                self.url,
                origin=self.origin,
                user_agent_header="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            self.running = True
            self._log(f"✓ 已连接: {self.url}")
            return True
        except Exception as e:
            self._log(f"✗ 连接失败: {e}")
            return False

    async def send(self, data: dict):
        """发送 JSON"""
        # 只对房间消息进行敏感词处理
        if data.get("c") == "SayInRoom" and "Msg" in data:
            data["Msg"] = self._censor_message(data["Msg"])
        msg = json.dumps(data, ensure_ascii=False)
        await self.ws.send(msg)
        self._log(f"→ {msg}")

    async def send_raw(self, msg: str):
        """发送原始字符串，不处理敏感词"""
        await self.ws.send(msg)
        self._log(f"→ {msg}")

    async def _send_menu(self):
        """发送菜单，不阻塞"""
        await self.send_msg("功能列表")
        await asyncio.sleep(1)
        await self.send_msg("1.查周榜/查月榜+道具名(可选)")
        await asyncio.sleep(1)
        await self.send_msg("2.喇叭总结/喇叭提问+分钟数(可选)")
        await asyncio.sleep(1)
        await self.send_msg("3.破解+房间号")
        await asyncio.sleep(1)
        await self.send_msg("4.查房+房间号")
        await asyncio.sleep(1)
        await self.send_msg("5.AI+问题")
        await asyncio.sleep(1)
        await self.send_msg("6.固定房间+房号")
        await asyncio.sleep(1)
        await self.send_msg("7.分析/锐评动态+用户ID")
        await asyncio.sleep(1)
        await self.send_msg("8.关注/取关+用户SID")
        await asyncio.sleep(1)
        await self.send_msg("9.自动跟随+用户SID / 取消跟随")
        await asyncio.sleep(1)
        await self.send_msg("10.开启自动换位 / 关闭自动换位")
        await asyncio.sleep(1)
        await self.send_msg("11.开启明星提醒 / 关闭明星提醒")
        await asyncio.sleep(1)
        await self.send_msg("12.聊天记录10 (可指定条数)")
        await asyncio.sleep(1)
        await self.send_msg("12.聊天记录+数字 / 查看最近N条聊天")


    async def send_msg(self, msg: str, color: str = "#FFFFFF"):
        """发送消息到房间，自动处理敏感词"""
        await self.send({"Act": "", "Color": color, "Msg": msg, "c": "SayInRoom"})

    async def login(self, token: str, device: str, p: str = ""):
        """发送登录消息"""
        await self.send({"i": token, "device": device, "p": p})
        await asyncio.sleep(0.3)
        await self.send({"c": "UserInfo"})
        await asyncio.sleep(0.3)
        await self.send({"c": "JoinHall"})
        # 自动跟随优先于固定房间
        await self._start_auto_follow()
        
        # 启动明星提醒
        if self._star_reminder:
            await self._start_star_reminder()

    async def _restart_auto_follow(self):
        """重启自动跟随（取消旧任务，启动新任务）"""
        # 取消旧的循环任务
        if self._auto_follow_task:
            self._auto_follow_task.cancel()
            self._auto_follow_task = None
        # 重置当前跟随的房间
        self._current_followed_room = ""
        # 启动新的跟随
        await self._start_auto_follow()

    async def _start_auto_follow(self):
        """启动自动跟随"""
        auto_follow_sid = self.get_auto_follow_sid()
        if not auto_follow_sid:
            # 没有自动跟随，使用固定房间
            await self._join_fixed_room()
            return

        self._log(f"启动自动跟随: sid={auto_follow_sid}")

        # 直接使用 json 中保存的 userId
        user_id = self.get_auto_follow_user_id()
        if not user_id:
            self._log("错误: json 中没有 userId，请先设置自动跟随")
            await self._join_fixed_room()
            return

        # 发送 PlayerInfo2 请求
        await self.send({"UserId": user_id, "c": "PlayerInfo2"})
        self._log(f"已发送PlayerInfo2请求: userId={user_id}")

        # 启动定时查询任务（每秒一次）
        if self._auto_follow_task:
            self._auto_follow_task.cancel()
        self._auto_follow_task = asyncio.create_task(self._auto_follow_loop(user_id))

    async def _auto_follow_loop(self, user_id: str):
        """自动跟随循环任务：每秒查询一次目标用户房间"""
        while self.running and self.get_auto_follow_sid():
            await asyncio.sleep(1)
            if not self.get_auto_follow_sid():
                break
            await self.send({"UserId": user_id, "c": "PlayerInfo2"})
            self._log(f"查询房间: userId={user_id}")

    async def _handle_player_info(self, msg: str):
        """处理 PlayerInfo 响应，提取房间号并进入房间"""
        auto_follow_sid = self.get_auto_follow_sid()
        if not auto_follow_sid:
            return

        # 提取 Room 字段（可能有引号也可能没有）
        room_match = re.search(r'"Room"\s*:\s*"?(\d+)"?', msg)
        if not room_match:
            # 查房失败，也尝试进入当前跟随的房间
            room_id = self._current_followed_room
            if room_id:
                self._log(f"查房失败，尝试跟随当前记录的房间: {room_id}")
                await self._join_followed_room(room_id)
            return

        room_id = room_match.group(1)
        if room_id and room_id != self._current_followed_room:
            self._log(f"检测到房间变化: {self._current_followed_room} -> {room_id}")
            self._current_followed_room = room_id
            await self._join_followed_room(room_id)

    async def _join_followed_room(self, room_id: str):
        """进入跟随的房间"""
        # 进入新房间
        await self.send({"RoomId": room_id, "Password": "", "c": "JoinRoom"})
        self._log(f"自动跟随进入房间: {room_id}")
        await asyncio.sleep(1)

        # 查询房间玩家位置，尝试换到主人旁边（这里是无视查房失败的）
        await self.send({"c": "SO_o", "n": f"Player{room_id}"})
        await asyncio.sleep(1)

        # 发送跟随语
        follow_msg = self.get_follow_message()
        if follow_msg:
            await asyncio.sleep(0.5)
            await self.send_msg(follow_msg, "#00FF00")
            self._log(f"发送跟随语: {follow_msg}")

        # 开启自动换位（如果查房失败，自动换位会使用当前跟随的房间）
        if self._auto_change_site:
            await self._start_auto_change_site()

    def _get_site_priority(self, current_site: int) -> list:
        """获取换位优先级列表
        房间布局：1-5第一排，6-10第二排，11-15第三排，16-20第四排
        优先左右，其次上下，都有人就不换
        """
        site = current_site
        # 确定在第几列（1-5）
        col = (site - 1) % 5
        # 确定在第几排（1-4）
        row = (site - 1) // 5 + 1
        
        priority = []
        
        # 同排左右邻居（右边优先，然后左边）
        if col == 0:
            priority.extend([site + 1])  # 右
        elif col == 4:
            priority.extend([site - 1])  # 左
        else:
            priority.extend([site + 1, site - 1])  # 右、左
        
        # 上下邻居（下面优先，然后上面）
        if row == 1:
            priority.extend([site + 5])  # 下
        elif row == 4:
            priority.extend([site - 5])  # 上
        else:
            priority.extend([site + 5, site - 5])  # 下、上
        
        # 过滤掉0和当前位置
        return [s for s in priority if s and s != site and 1 <= s <= 20]

    async def _start_auto_change_site(self):
        """启动自动换位任务"""
        if self._auto_change_site_task:
            self._auto_change_site_task.cancel()
        self._auto_change_site_task = asyncio.create_task(self._auto_change_site_loop())

    async def _stop_auto_change_site(self):
        """停止自动换位任务"""
        if self._auto_change_site_task:
            self._auto_change_site_task.cancel()
            self._auto_change_site_task = None

    async def _auto_change_site_loop(self):
        """自动换位循环：每秒查询房间玩家位置"""
        while self.running and self._auto_change_site:
            await asyncio.sleep(1)
            if not self._auto_change_site:
                break
            # 查询当前房间玩家
            room_id = self._current_followed_room
            if room_id:
                await self.send({"c": "SO_o", "n": f"Player{room_id}"})

    async def _handle_auto_change_site(self, msg: str):
        """处理房间同步消息，自动换位"""
        if not self._auto_change_site:
            return
        
        # 解析玩家列表
        players = []
        # 使用贪婪匹配解析每个玩家的完整数据
        player_blocks = re.findall(r'\[1,"(\d+)",\{(.*?)\}\]', msg, re.DOTALL)
        for user_id, block in player_blocks:
            # 排除机器人自己
            if user_id == self._my_user_id:
                continue
            site_match = re.search(r'"RoomSite"\s*:\s*(\d+)', block)
            if site_match:
                players.append({"user_id": user_id, "site": int(site_match.group(1))})
        
        if not players:
            return
        
        self._auto_change_site_last_players = players
        
        # 找到跟随者的位置
        follow_user_id = str(self._auto_follow_user_id)
        followed_site = None
        for p in players:
            if str(p["user_id"]) == follow_user_id:
                followed_site = p["site"]
                break
        
        if not followed_site:
            return
        
        # 检查位置是否变化（首次进入房间时 _last_followed_site 为 0，也需要换位）
        if followed_site == self._last_followed_site and self._last_followed_site != 0:
            return
        
        self._log(f"跟随者位置变化: {self._last_followed_site} -> {followed_site}")
        self._last_followed_site = followed_site

        # 找出空位（排除0）
        occupied_sites = {p["site"] for p in players if p["site"] != 0}
        empty_sites = [s for s in range(1, 21) if s not in occupied_sites]

        if not empty_sites:
            self._log("房间已满，无法换位")
            return

        # 获取优先级列表（右边>左边>下>上）
        priority = self._get_site_priority(followed_site)

        # 从优先级列表中选择第一个空位
        target_site = None
        for p in priority:
            if p in empty_sites:
                target_site = p
                break

        # 如果优先级位置都满了，用任意空位
        if target_site is None:
            target_site = empty_sites[0]

        self._log(f"自动换位: 跟随者在{followed_site}，选择{target_site}")
        await self.handle_change_site(str(target_site), send_follow_msg=True)

    async def _join_fixed_room(self):
        """加入固定房间"""
        fixed_room = self.get_fixed_room()
        if fixed_room:
            self._log(f"加入固定房间: {fixed_room}")
            await self.send({"RoomId": fixed_room, "Password": "", "c": "JoinRoom"})

    async def _delayed_return_to_room(self, fixed_room: str, password: str = None):
        """延迟返回固定房间，破解成功时先返回房间再回答密码"""
        if fixed_room:
            await self.send({"RoomId": fixed_room, "Password": "", "c": "JoinRoom"})
            # 等待进入房间
            await asyncio.sleep(1)
        if password:
            await self.send_msg(f"破解成功！密码: {password}", "#00FF00")

    async def show_chat_history(self, count: int = 10):
        """查看聊天记录"""
        log_path = "bot.log"
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 倒序查找 RoomSay 开头的行
            room_says = []
            for line in reversed(lines):
                if '← RoomSay{' in line:
                    # 提取消息内容
                    msg_match = re.search(r'"m"\s*:\s*"([^"]*)"', line)
                    # 提取用户名 (u数组的第3个元素)
                    user_match = re.search(r'"u"\s*:\s*\[[^\]]*,"([^"]+)"', line)
                    # 提取时间戳
                    time_match = re.search(r'\[([^\]]+)\]', line)
                    
                    if msg_match and user_match:
                        msg = msg_match.group(1)
                        user = user_match.group(1)
                        time = time_match.group(1) if time_match else ""
                        room_says.append((time, user, msg))
                        
                        if len(room_says) >= count:
                            break
            
            if not room_says:
                await self.send_msg("暂无聊天记录", "#888888")
                return
            
            # 倒转回来（从旧到新）
            room_says.reverse()
            
            result = []
            for i, (time, user, msg) in enumerate(room_says, 1):
                # 截断太长的消息
                display_msg = msg[:30] + "..." if len(msg) > 30 else msg
                result.append(f"{i}.[{time}]{user}: {display_msg}")
            
            output = "聊天记录:\n" + "\n".join(result)
            await self.send_msg(output, "#FFFFFF")
            self._log(f"查看聊天记录: {count}条")
            
        except Exception as e:
            self._log(f"读取聊天记录失败: {e}")
            await self.send_msg("读取聊天记录失败", "#FF0000")

    async def handle_room_crack(self, room_id: str):
        """破解房间密码"""
        if self._room_cracking:
            await self.send_msg("正在破解中，请稍后...", "#FFA500")
            return
        
        self._room_cracking = True
        self._crack_pending = {
            "room_id": room_id,
            "current_password": 0,
            "stage": 1,  # 1: 000-999, 2: 0-9, 3: 00-99
            "last_heartbeat": time.time()
        }
        fixed_room = self.get_fixed_room()
        
        await self.send_msg(f"开始破解房间 {room_id}...", "#00FF00")
        
        # 发送第一个密码尝试 (000)
        password = "000"
        self._log(f"尝试密码: {password}")
        await self.send({"RoomId": room_id, "Password": password, "c": "JoinRoom"})

    async def handle_user_analysis(self, sid: str):
        """分析用户动态"""
        # 固定 u 参数
        u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

        try:
            # 调用第一个接口获取用户真实ID
            myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={u}"
            self._log(f"获取用户信息: {myf_url}")
            
            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()
            
            if data.get("msg") != "OK" or not data.get("data"):
                await self.send_msg(f"未找到用户: {sid}", "#FF0000")
                return
            
            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info["userName"]
            integral = user_info["integral"]
            online = "在线" if user_info["online"] == 2 else "离线"
            is_boy = "男" if user_info.get("isboy", True) else "女"
            
            # 调用第二个接口获取用户动态
            post_url = f"https://t1.ss911.cn/Sns/PostUser.ss?userid={user_id}&p=1&ps=10&u={u}"
            self._log(f"获取用户动态: {post_url}")
            
            response = await asyncio.to_thread(requests.get, post_url, timeout=10)
            posts_data = response.json()
            
            if not posts_data.get("list"):
                await self.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
                return
            
            posts = posts_data["list"]
            
            # 提取动态内容供AI分析
            posts_text = []
            for i, post in enumerate(posts[:10], 1):
                body = post.get("body", "")
                addtime = post.get("addtime", "")
                goodnum = post.get("goodnum", 0)
                replynum = post.get("replynum", 0)
                posts_text.append(f"动态{i}[{addtime}]: {body} (点赞:{goodnum}, 评论:{replynum})")
            
            posts_summary = "\n".join(posts_text)

            # 调用AI分析
            summarizer = AISummarizer(AI_API_KEY, AI_BASE_URL, AI_MODEL_NAME)

            prompt = f"""用户信息：
- 名字: {user_name}
- ID: {user_id}
- 积分: {integral}
- 在线状态: {online}
- 性别: {is_boy}

最近动态：
{posts_summary}

请根据以上信息，从以下角度构建用户的人物画像：
1. 推断其年龄段、性格特点、可能的职业或身份
2. 分析其社交风格和互动习惯，包括与朋友的互动模式
3. 推断兴趣爱好、生活状态和情感状态
4. 分析其发布内容的质量、频率和模式
5. 总结其活跃模式和社区行为特点
6. 识别一些有趣的细节或有趣的观察

回复格式：先输出【人物画像】标题，然后从以上角度详细描述，用简洁有趣的语言，总字数控制在200字以内。"""
            
            headers = {
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": AI_MODEL_NAME,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是游戏社区用户分析助手。请简洁分析用户特征和动态特点，用中文回复，控制在100字以内。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 200
            }
            
            response = await asyncio.to_thread(
                requests.post,
                f"{AI_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=15
            )
            
            result = response.json()
            if "choices" in result and result["choices"]:
                analysis = result["choices"][0]["message"]["content"]
                msg_text = f"【{user_name}】分析结果:\n{analysis}"
            else:
                msg_text = f"【{user_name}】\n积分:{integral} | {online} | {is_boy}\n动态:{len(posts)}条"
            
            await self.send_msg(msg_text)
            
        except Exception as e:
            self._log(f"分析用户失败: {e}")
            await self.send_msg(f"分析失败: {str(e)}", "#FF0000")

    async def handle_user_roast(self, sid: str):
        """锐评用户动态"""
        u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

        try:
            myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={u}"
            self._log(f"锐评-获取用户信息: {myf_url}")

            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info["userName"]

            post_url = f"https://t1.ss911.cn/Sns/PostUser.ss?userid={user_id}&p=1&ps=10&u={u}"
            self._log(f"锐评-获取用户动态: {post_url}")

            response = await asyncio.to_thread(requests.get, post_url, timeout=10)
            posts_data = response.json()

            if not posts_data.get("list"):
                await self.send_msg(f"用户 {user_name} 暂无动态", "#FFA500")
                return

            posts = posts_data["list"]

            posts_text = []
            for i, post in enumerate(posts[:10], 1):
                body = post.get("body", "")
                addtime = post.get("addtime", "")
                goodnum = post.get("goodnum", 0)
                replynum = post.get("replynum", 0)
                posts_text.append(f"动态{i}[{addtime}]: {body} (点赞:{goodnum}, 评论:{replynum})")

            posts_summary = "\n".join(posts_text)

            headers = {
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": AI_MODEL_NAME,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是毒舌网友，专门锐评游戏玩家的朋友圈动态。用最犀利、最损、最阴阳怪气的语言进行锐评，要直接、刻薄、毫不留情。可以调侃用户的动态内容、点赞数、评论数、发布频率、用户名等一切可以吐槽的点。要有梗、有攻击性、让人看了会心一笑。回复控制在100字以内，要一针见血，不要废话。"
                    },
                    {
                        "role": "user",
                        "content": f"用户【{user_name}】的动态如下，请锐评：\n{posts_summary}"
                    }
                ],
                "temperature": 1.0,
                "max_tokens": 200
            }

            response = await asyncio.to_thread(
                requests.post,
                f"{AI_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=15
            )

            result = response.json()
            if "choices" in result and result["choices"]:
                roast = result["choices"][0]["message"]["content"]
                msg_text = f"【{user_name}】锐评:\n{roast}"
            else:
                msg_text = f"【{user_name}】锐评失败"

            await self.send_msg(msg_text, "#FF69B4")

        except Exception as e:
            self._log(f"锐评用户失败: {e}")
            await self.send_msg(f"锐评失败: {str(e)}", "#FF0000")

    async def handle_follow(self, sid: str):
        """关注用户"""
        u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"
        follow_u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

        try:
            myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={u}"
            self._log(f"关注-获取用户信息: {myf_url}")

            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info["userName"]

            follow_url = f"https://t1.ss911.cn/User/FriendDo.ss?type=3&fid={user_id}&both=1&u={follow_u}"
            self._log(f"关注用户: {follow_url}")

            response = await asyncio.to_thread(requests.get, follow_url, timeout=10)
            result = response.json()

            if result.get("msg") == "OK":
                await self.send_msg(f"已关注 {user_name}", "#00FF00")
            else:
                await self.send_msg(f"关注失败: {result.get('msg', '未知错误')}", "#FF0000")

        except Exception as e:
            self._log(f"关注用户失败: {e}")
            await self.send_msg(f"关注失败: {str(e)}", "#FF0000")

    async def handle_unfollow(self, sid: str):
        """取关用户"""
        u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"
        follow_u = "%2BNemHgNs1FoC3oABc0cSUeB6hvpcqbgIMhExuooxtmQ%3D"

        try:
            myf_url = f"https://t1.ss911.cn/User/MyF.ss?p=1&t=5&sid={sid}&u={u}"
            self._log(f"取关-获取用户信息: {myf_url}")

            response = await asyncio.to_thread(requests.get, myf_url, timeout=10)
            data = response.json()

            if data.get("msg") != "OK" or not data.get("data"):
                await self.send_msg(f"未找到用户: {sid}", "#FF0000")
                return

            user_info = data["data"][0]
            user_id = user_info["userId"]
            user_name = user_info["userName"]

            unfollow_url = f"https://t1.ss911.cn/User/FriendDo.ss?type=4&fid={user_id}&both=1&u={follow_u}"
            self._log(f"取关用户: {unfollow_url}")

            response = await asyncio.to_thread(requests.get, unfollow_url, timeout=10)
            result = response.json()

            if result.get("msg") == "OK":
                await self.send_msg(f"已取关 {user_name}", "#FFFF00")
            else:
                await self.send_msg(f"取关失败: {result.get('msg', '未知错误')}", "#FF0000")

        except Exception as e:
            self._log(f"取关用户失败: {e}")
            await self.send_msg(f"取关失败: {str(e)}", "#FF0000")

    def _handle_crack_response(self, msg: str, fixed_room: str):
        """处理破解响应，在 recv_loop 中调用"""
        if not self._room_cracking or not self._crack_pending:
            return None
        
        room_id = self._crack_pending["room_id"]
        stage = self._crack_pending.get("stage", 1)
        
        if "InvalidPassword" in msg:
            # 检查是否是目标房间
            room_match = re.search(r'"RoomId"\s*:\s*"?(\d+)"?', msg)
            if room_match and room_match.group(1) != room_id:
                return None  # 不是目标房间的响应，跳过
            # 密码错误，继续尝试下一个
            self._crack_pending["current_password"] += 1
            
            if stage == 1:
                # 阶段1: 000-999
                if self._crack_pending["current_password"] >= 1000:
                    # 进入阶段2: 0-9
                    self._crack_pending["current_password"] = 0
                    self._crack_pending["stage"] = 2
                    password = "0"
                    self._log(f"阶段1完成，进入阶段2: 尝试密码: {password}")
                    return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom", "delay": True}
                password = f"{self._crack_pending['current_password']:03d}"
                
            elif stage == 2:
                # 阶段2: 0-9
                if self._crack_pending["current_password"] >= 10:
                    # 进入阶段3: 00-99
                    self._crack_pending["current_password"] = 0
                    self._crack_pending["stage"] = 3
                    password = "00"
                    self._log(f"阶段2完成，进入阶段3: 尝试密码: {password}")
                    return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom", "delay": True}
                password = f"{self._crack_pending['current_password']}"
                
            elif stage == 3:
                # 阶段3: 00-99
                if self._crack_pending["current_password"] >= 100:
                    # 全部尝试完毕
                    self._room_cracking = False
                    self._crack_pending = None
                    return "crack_failed"
                password = f"{self._crack_pending['current_password']:02d}"
            
            if self._crack_pending["current_password"] > 0 and self._crack_pending["current_password"] % 50 == 0:
                return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom", "delay": True}

            self._log(f"尝试密码: {password}")
            return {"action": "try_password", "RoomId": room_id, "Password": password, "c": "JoinRoom"}
        
        elif msg.startswith("JoinRoom"):
            # 检查是否是目标房间的 JoinRoom
            room_match = re.search(r'"RoomId"\s*:\s*"?(\d+)"?', msg)
            if room_match and room_match.group(1) == room_id:
                # 破解成功
                if stage == 1:
                    password = f"{self._crack_pending['current_password']:03d}"
                elif stage == 2:
                    password = f"{self._crack_pending['current_password']}"
                else:
                    password = f"{self._crack_pending['current_password']:02d}"
                self._room_cracking = False
                self._crack_pending = None
                return {"action": "crack_success", "password": password, "fixed_room": fixed_room}
        
        return None

    async def handle_rank_query(self, content: str):
        """处理排行榜查询"""
        self._log(f"处理排行榜查询: {content}")

        # 检查是否只输入"查周榜"或"查月榜"（不带道具名）
        rank_type = "week"
        
        # 支持范围查询: 查周榜2-8 或 查月榜1-10
        range_match = re.search(r'查(周|月)榜(\d+)-(\d+)', content)
        if range_match:
            rank_type = "month" if range_match.group(1) == "月" else "week"
            start_rank = int(range_match.group(2))
            end_rank = int(range_match.group(3))
            self._log(f"查询范围排行榜, 类型: {rank_type}, 范围: {start_rank}-{end_rank}")
            await self._handle_all_tools_rank(rank_type, start_rank, end_rank)
            return
        
        if "查月榜" in content and content.strip() in ["查月榜", "查月榜 "]:
            rank_type = "month"
            self._log(f"查询全道具排行榜, 类型: {rank_type}")
            await self._handle_all_tools_rank(rank_type)
            return
        elif content.strip() in ["查周榜", "查周榜 "]:
            rank_type = "week"
            self._log(f"查询全道具排行榜, 类型: {rank_type}")
            await self._handle_all_tools_rank(rank_type)
            return

        # 提取道具名和榜单类型
        if "查月榜" in content:
            rank_type = "month"
            match = re.search(r'查月榜\s*(.+)', content)
        else:
            match = re.search(r'查周榜\s*(.+)', content)

        if not match:
            return

        tool_name = match.group(1).strip()
        self._log(f"查询道具: {tool_name}, 类型: {rank_type}")

        # 查询排行榜
        results, price = self.rank_query.query_rank(tool_name, rank_type)
        if results is None:
            await self.send_msg("未找到该道具，请稍后再试", "#FF0000")
            return

        if not results:
            await self.send_msg(f"暂无{tool_name}的{'月' if rank_type == 'month' else '周'}榜数据", "#FF0000")
            return

        # 每1秒发送一条
        for item in results:
            num = item['num']
            total_price = num * price
            msg_text = f"{item['userName']}: {num} 总守护:{int(total_price)}"
            await self.send_msg(msg_text)
            await asyncio.sleep(1.5)

    async def _handle_all_tools_rank(self, rank_type: str = "week", start_rank: int = 1, end_rank: int = 30):
        """处理查询所有道具排行榜
        
        Args:
            rank_type: week 或 month
            start_rank: 起始排名，默认1
            end_rank: 结束排名，默认30
        """
        await self.send_msg(f"正在查询{'月' if rank_type == 'month' else '周'}榜...", "#00FF00")

        results = self.rank_query.query_all_tools_rank(rank_type)
        if not results:
            await self.send_msg(f"暂无{'月' if rank_type == 'month' else '周'}榜数据", "#FF0000")
            return

        # 发送表头
        header = f"【{'本' if rank_type == 'week' else '本'}月道具榜】" if start_rank == 1 and end_rank == 30 else f"【{'本' if rank_type == 'week' else '本'}月道具榜 第{start_rank}-{end_rank}名】"
        await self.send_msg(header, "#FFFF00")
        await asyncio.sleep(1.5)

        # 筛选范围内的排名
        filtered_results = [item for item in results if start_rank <= item[0] <= end_rank]
        
        if not filtered_results:
            await self.send_msg(f"暂无第{start_rank}-{end_rank}名数据", "#FF0000")
            return

        for rank, username, tool_name, num, total_price in filtered_results:
            msg_text = f"{rank}. {username}: {tool_name} {num} 总守护:{int(total_price)}"
            await self.send_msg(msg_text)
            await asyncio.sleep(1.5)

    def _read_recent_speaker_messages(self, minutes: int = 5) -> list:
        """从日志文件读取最近N分钟的喇叭消息"""
        messages = []

        log_file = self.log_path if hasattr(self, 'log_path') else os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
        self._log(f"[DEBUG] 读取日志文件: {log_file}")

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    # 匹配喇叭消息格式: [时间戳] ← Speaker{...}
                    match = re.match(r'\[(\d{2}:\d{2}:\d{2})\] ← Speaker\{', line)
                    if not match:
                        continue

                    timestamp_str = match.group(1)

                    # 提取从 Speaker{ 开始的内容
                    json_start = line.find("Speaker{")
                    if json_start == -1:
                        continue
                    # 跳过 "Speaker" 前缀，从 "{" 开始解析JSON
                    json_str = line[json_start + 7:]

                    # 解析JSON数据
                    try:
                        data = json.loads(json_str)
                        msg = data.get("Msg", "")
                        user_name = data.get("UserName", "未知")
                        # 过滤掉机器人的消息
                        if user_name == self._bot_name:
                            continue
                        # 过滤掉菜单、功能列表等机器人发出的消息
                        if msg in ["功能列表", "1.查周榜/查月榜+道具名(可选)", "2.喇叭总结/喇叭提问+分钟数(可选)", "3.破解+房间号", "4.查房+房间号", "5.AI+问题", "6.固定房间+房号"]:
                            continue
                        if msg:
                            messages.append({
                                "timestamp": timestamp_str,
                                "userName": user_name,
                                "msg": msg
                            })
                    except:
                        continue
        except Exception as e:
            self._log(f"读取喇叭消息失败: {e}")
            return []

        # 过滤最近N分钟的消息
        now = datetime.now()
        current_time_str = now.strftime("%H:%M:%S")
        cutoff_time_str = (now - timedelta(minutes=minutes)).strftime("%H:%M:%S")

        self._log(f"[DEBUG] 当前时间: {current_time_str}, 截止时间: {cutoff_time_str}, 总消息数: {len(messages)}")

        recent_messages = []
        for msg in messages:
            msg_time = msg["timestamp"]

            # 判断消息是否在时间范围内（处理跨午夜情况）
            if cutoff_time_str <= current_time_str:
                # 正常情况：没有跨午夜
                if cutoff_time_str <= msg_time <= current_time_str:
                    recent_messages.append(msg)
            else:
                # 跨午夜了：截止时间是昨天，今天的时间也可能是昨天
                if msg_time >= cutoff_time_str or msg_time <= current_time_str:
                    recent_messages.append(msg)

        self._log(f"[DEBUG] 过滤后消息数: {len(recent_messages)}")
        return [{"userName": m["userName"], "msg": m["msg"]} for m in recent_messages]

    async def handle_ai_summary(self, content: str):
        """处理总结喇叭请求"""
        self._log(f"处理总结喇叭: {content}")

        # 提取分钟数，默认为5分钟
        match = re.search(r'(总结喇叭|喇叭总结)(\d+)', content)
        minutes = int(match.group(2)) if match else 5

        self._log(f"正在读取最近{minutes}分钟的喇叭消息...")

        # 读取喇叭消息
        messages = self._read_recent_speaker_messages(minutes)
        self._log(f"读取到{len(messages)}条喇叭消息")

        if not messages:
            await self.send_msg(f"最近{minutes}分钟暂无喇叭消息", "#FFA500")
            return

        # 调用总结
        await self.send_msg(f"正在总结最近{minutes}分钟的{len(messages)}条喇叭...", "#00FF00")

        summary = self.ai_summarizer.summarize(messages, minutes)

        # 发送总结结果，分段发送以防消息过长
        max_len = 100
        for i in range(0, len(summary), max_len):
            part = summary[i:i + max_len]
            await self.send_msg(part, "#00FFFF")
            await asyncio.sleep(1.5)

    async def handle_ai_question(self, content: str):
        """处理喇叭提问请求"""
        self._log(f"处理喇叭提问: {content}")

        # 提取问题内容（去掉"喇叭提问"或"提问喇叭"）
        question = content.replace("喇叭提问", "").replace("提问喇叭", "").strip()
        if not question:
            await self.send_msg("请输入要查询的问题，如：喇叭提问有没有人征婚", "#FFA500")
            return

        minutes = 60  # 默认读取60分钟

        self._log(f"正在读取最近{minutes}分钟的喇叭消息...")

        # 读取喇叭消息
        messages = self._read_recent_speaker_messages(minutes)
        self._log(f"读取到{len(messages)}条喇叭消息")

        if not messages:
            await self.send_msg(f"最近{minutes}分钟暂无喇叭消息", "#FFA500")
            return

        # 调用AI回答
        await self.send_msg(f"正在查询最近{minutes}分钟的喇叭...", "#00FF00")

        answer = self.ai_summarizer.answer_question(messages, question, minutes)

        # 发送回答结果，分段发送以防消息过长
        max_len = 100
        for i in range(0, len(answer), max_len):
            part = answer[i:i + max_len]
            await self.send_msg(part, "#00FFFF")
            await asyncio.sleep(1.5)

    async def handle_ai_chat(self, content: str):
        """处理AI直接回答请求"""
        self._log(f"处理AI问答: {content}")

        # 提取问题内容（去掉"AI"）
        question = content.replace("AI", "").strip()
        if not question:
            await self.send_msg("请输入要查询的问题，如：AI今天天气怎么样", "#FFA500")
            return

        await self.send_msg(f"正在思考...", "#00FF00")

        # 调用AI直接回答
        answer = self.ai_summarizer.direct_answer(question)

        # 发送回答结果，分段发送以防消息过长
        max_len = 100
        for i in range(0, len(answer), max_len):
            part = answer[i:i + max_len]
            await self.send_msg(part, "#00FFFF")
            await asyncio.sleep(1.5)

    async def handle_change_site(self, site: str, send_follow_msg: bool = False):
        """处理换位请求（权限用户可用）
        send_follow_msg=True: 自动换位，先上树再换位，换位后发跟随语
        send_follow_msg=False: 命令换位，先上树再换位，不发跟随语
        """
        self._log(f"换位到: {site}, send_follow_msg={send_follow_msg}")

        # 先上树
        msg1 = {"Site": "-1", "FSite": "", "c": "ChangeSite"}
        await self.send(msg1)
        self._log(f"发送上树: {msg1}")
        await asyncio.sleep(0.3)

        # 再换位
        msg2 = {"Site": site, "c": "ChangeSite"}
        await self.send(msg2)
        self._log(f"发送换位: {msg2}")

        # 仅自动换位时发跟随语
        if send_follow_msg:
            follow_msg = self.get_follow_message()
            if follow_msg:
                await asyncio.sleep(0.5)
                await self.send_msg(follow_msg, "#00FF00")
                self._log(f"发送跟随语: {follow_msg}")

    async def run(self):
        """监听消息 + 接收用户输入"""
        self._log("⏳ 开始监听... (输入内容发送，空行心跳)")
        self._log("-" * 50)

        # 保存登录参数用于重连
        login_token = None
        login_device = None
        login_p = None

        async def recv_loop():
            """接收服务端消息"""
            while self.running:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    self._log(f"← {msg}")

                    # 处理查房回调（用当前连接发起的查询）
                    if msg.startswith("SO_Sync{"):
                        m = re.search(r'"n"\s*:\s*"Player(\d+)"', msg)
                        if m:
                            room_id = m.group(1)
                            if room_id in self._player_query_handlers:
                                self._player_query_handlers[room_id](msg)
                        m2 = re.search(r'"n"\s*:\s*"Room(\d+)"', msg)
                        if m2:
                            room_id = m2.group(1)
                            if room_id in self._player_query_handlers:
                                self._player_query_handlers[room_id](msg)

                    # 记录机器人名字和userId
                    if msg.startswith("UserInfo{"):
                        m = re.search(r'"UserName"\s*:\s*"([^"]+)"', msg)
                        if m:
                            self._bot_name = m.group(1)
                            self._log(f"机器人名字: {self._bot_name}")
                        # 提取userId
                        uid_m = re.search(r'"UserId"\s*:\s*"?(\d+)"?', msg)
                        if uid_m:
                            self._my_user_id = uid_m.group(1)
                            self._log(f"机器人userId: {self._my_user_id}")

                    # 处理 SM/RoomSay 消息中的内容
                    if msg.startswith("SM{") or msg.startswith("RoomSay{"):
                        if msg.startswith("RoomSay{"):
                            # 从 RoomSay 提取用户ID进行权限检查
                            user_id = None
                            m = re.search(r'"u"\s*:\s*\[\s*\d+\s*,\s*(\d+)', msg)
                            if m:
                                user_id = m.group(1)
                                # 权限检查：如果有权限列表且用户不在列表中，跳过
                                if len(self._allowed_users) > 0 and user_id not in self._allowed_users:
                                    self._log(f"用户 {user_id} 不在权限列表中，跳过")
                                    continue

                        m = re.search(r'"m"\s*:\s*"([^"]*)"', msg)
                        if m:
                            content = m.group(1)
                            # 优先检查"菜单"
                            if "菜单" in content:
                                asyncio.create_task(self._send_menu())
                                continue
                            # 检查是否包含"查周榜"或"查月榜"
                            elif "查周榜" in content or "查月榜" in content:
                                asyncio.create_task(self.handle_rank_query(content))
                            # 检查是否包含"总结喇叭"或"喇叭总结"
                            elif "总结喇叭" in content or "喇叭总结" in content:
                                asyncio.create_task(self.handle_ai_summary(content))
                            # 检查是否包含"喇叭提问"或"提问喇叭"
                            elif "喇叭提问" in content or "提问喇叭" in content:
                                asyncio.create_task(self.handle_ai_question(content))
                            # 检查是否包含"查房"
                            elif content.startswith("查房"):
                                match = re.search(r'查房(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_room_query(match.group(1)))
                            # 检查是否包含"总结房间"
                            elif "总结房间" in content or "房间总结" in content:
                                match = re.search(r'(?:总结房间|房间总结)\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_room_summary(int(match.group(1))))
                            # 检查是否包含"聊天记录"
                            elif content.startswith("聊天记录"):
                                match = re.search(r'聊天记录\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_chat_history(int(match.group(1))))
                                else:
                                    asyncio.create_task(self.handle_chat_history(10))
                            # 检查是否包含"固定房间"或"取消固定"
                            elif content.startswith("固定房间"):
                                match = re.search(r'固定房间\s*(\d+)', content)
                                if match:
                                    room_id = match.group(1)
                                    self.set_fixed_room(room_id)
                                    asyncio.create_task(self.send_msg(f"已设置固定房间: {room_id}"))
                            elif "取消固定" in content:
                                self.clear_fixed_room()
                                asyncio.create_task(self.send_msg("已取消固定房间"))
                            # 检查是否包含"自动跟随"或"取消跟随"
                            elif content.startswith("自动跟随"):
                                match = re.search(r'自动跟随\s*(\d+)', content)
                                if match:
                                    sid = match.group(1)
                                    await self.set_auto_follow(sid)
                                    asyncio.create_task(self.send_msg(f"已设置自动跟随: {sid}"))
                            elif "取消跟随" in content:
                                self.clear_auto_follow()
                                self._current_followed_room = ""
                                asyncio.create_task(self.send_msg("已取消自动跟随"))
                            elif "开启自动换位" in content:
                                await self.toggle_auto_change_site(True)
                                asyncio.create_task(self.send_msg(f"自动换位: {'开启' if self._auto_change_site else '关闭'}"))
                            elif "关闭自动换位" in content:
                                await self.toggle_auto_change_site(False)
                                asyncio.create_task(self.send_msg(f"自动换位: {'开启' if self._auto_change_site else '关闭'}"))
                            elif "开启明星提醒" in content:
                                await self.toggle_star_reminder(True)
                                asyncio.create_task(self.send_msg(f"明星提醒: {'开启' if self._star_reminder else '关闭'}"))
                            elif "关闭明星提醒" in content:
                                await self.toggle_star_reminder(False)
                                asyncio.create_task(self.send_msg(f"明星提醒: {'开启' if self._star_reminder else '关闭'}"))
                            # 检查是否包含"跟随语"（仅主人可用）
                            elif content.startswith("跟随语"):
                                if user_id is not None and user_id in self._owners:
                                    msg_content = content[3:].strip()
                                    if msg_content:
                                        self.set_follow_message(msg_content)
                                        asyncio.create_task(self.send_msg(f"已设置跟随语: {msg_content}"))
                                    else:
                                        current_msg = self.get_follow_message()
                                        asyncio.create_task(self.send_msg(f"当前跟随语: {current_msg if current_msg else '未设置'}"))
                                else:
                                    asyncio.create_task(self.send_msg("只有主人才能设置跟随语"))
                            # 检查是否包含"破解"
                            elif "破解" in content:
                                match = re.search(r'破解\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_room_crack(match.group(1)))
                            # 检查是否包含"添加权限"（仅主人可用）
                            elif "添加权限" in content:
                                if user_id is not None and user_id in self._owners:
                                    match = re.search(r'添加权限\s*(\d+)', content)
                                    if match:
                                        target_user = match.group(1)
                                        self.add_allowed_user(target_user)
                                        asyncio.create_task(self.send_msg(f"添加成功"))
                            # 检查是否包含"删除权限"（仅主人可用）
                            elif "删除权限" in content:
                                if user_id is not None and user_id in self._owners:
                                    match = re.search(r'删除权限\s*(\d+)', content)
                                    if match:
                                        target_user = match.group(1)
                                        self.remove_allowed_user(target_user)
                                        asyncio.create_task(self.send_msg(f"删除成功"))
                            # 检查是否包含"锐评动态"
                            elif content.startswith("锐评动态") or "锐评动态" in content:
                                match = re.search(r'锐评动态\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_user_roast(match.group(1)))
                            # 检查是否包含"关注"
                            elif content.startswith("关注"):
                                match = re.search(r'关注\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_follow(match.group(1)))
                            # 检查是否包含"取关"
                            elif content.startswith("取关"):
                                match = re.search(r'取关\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_unfollow(match.group(1)))
                            # 检查是否包含"分析动态"
                            elif content.startswith("分析动态") or "分析动态" in content:
                                match = re.search(r'分析动态\s*(\d+)', content)
                                if match:
                                    asyncio.create_task(self.handle_user_analysis(match.group(1)))
                            # 检查是否包含"AI"
                            elif content.startswith("AI"):
                                asyncio.create_task(self.handle_ai_chat(content))
                            # 检查是否包含"上树"或"换位"（权限用户可用）
                            elif content.startswith("#上树"):
                                asyncio.create_task(self.handle_change_site("-1", send_follow_msg=False))
                            elif content.startswith("#换位"):
                                match = re.search(r'#换位\s*(\d+)', content)
                                if match:
                                    site = int(match.group(1))
                                    if 1 <= site <= 20:
                                        asyncio.create_task(self.handle_change_site(str(site), send_follow_msg=False))
                                    else:
                                        asyncio.create_task(self.send_msg("换位只支持1-20"))

                    # 处理 SO_Sync 响应（查房结果）
                    if msg.startswith("SO_Sync{") and self._room_query_pending is not None:
                        parsed = self._parse_room_sync(msg)
                        room_id = self._room_query_pending["room_id"]
                        sync_n = parsed.get("n", "")

                        if sync_n == f"Room{room_id}":
                            self._room_query_pending["room_result"] = parsed
                            self._room_query_pending["room_event"].set()
                        elif sync_n == f"Player{room_id}":
                            self._room_query_pending["players"] = parsed.get("players", [])
                            self._room_query_pending["player_event"].set()

                    # 自动换位处理（跟随状态）
                    if msg.startswith("SO_Sync{") and self._auto_change_site:
                        asyncio.create_task(self._handle_auto_change_site(msg))

                    # 自动处理邀请：收到 Invite 后回复 LeaveRoom
                    if msg.startswith("Invite{"):
                        m = re.search(r'"FromUserName"\s*:\s*"([^"]*)"', msg)
                        r = re.search(r'"RoomId"\s*:\s*"?(\d+)"?', msg)
                        if m and r:
                            username = m.group(1)
                            room_id = r.group(1)
                            reply = {"ToRoomId": room_id, "FromUserName": username, "c": "LeaveRoom"}
                            await self.send(reply)

                    # 处理 PlayerInfo2 响应（自动跟随）
                    if msg.startswith("PlayerInfo{") or "PlayerInfo2" in msg:
                        await self._handle_player_info(msg)

                    # 处理破解房间响应
                    fixed_room = self.get_fixed_room()
                    crack_result = self._handle_crack_response(msg, fixed_room)
                    if crack_result:
                        if crack_result == "crack_failed":
                            asyncio.create_task(self.send_msg("破解失败，未找到有效密码", "#FF0000"))
                        elif isinstance(crack_result, dict):
                            if crack_result.get("action") == "try_password":
                                if crack_result.get("delay"):
                                    await asyncio.sleep(5)  # 每50个密码暂停5秒
                                await self.send(crack_result)
                            elif crack_result.get("action") == "crack_success":
                                asyncio.create_task(self._delayed_return_to_room(crack_result['fixed_room'], crack_result['password']))
                            elif crack_result.get("action") == "heartbeat":
                                await self.send_raw("p")

                    # 自动心跳：每30秒发送一次
                    now = time.time()
                    if now - self._last_heartbeat >= 30:
                        self._last_heartbeat = now
                        await self.send_raw("p")

                    # 处理 jump 消息（进房失败）
                    if msg.startswith("jump{"):
                        m = re.search(r'"r"\s*:\s*"?(\d+)"?', msg)
                        l = re.search(r'"l"\s*:\s*"?(\d+)"?', msg)
                        if m and l:
                            jump_room = m.group(1)
                            jump_line = l.group(1)
                            self._log(f"进房失败，jump到房间{jump_room}线路{jump_line}")
                            self._join_fail_count += 1
                            
                            # 如果失败次数超过阈值，尝试切换服务器
                            if self._join_fail_count >= 3 and self._servers:
                                self._join_fail_count = 0
                                self._current_server_index = (self._current_server_index + 1) % len(self._servers)
                                ws_url, http_url = self._servers[self._current_server_index]
                                self._log(f"切换到服务器: {ws_url}")
                                self.url = ws_url
                                self.origin = http_url
                                # 关闭旧连接
                                try:
                                    await self.ws.close()
                                except:
                                    pass
                                # 重新连接
                                await asyncio.sleep(1)
                                if await self.connect():
                                    self._log("重连成功，重新登录...")
                                    await self.login(
                                        getattr(self, '_login_token', ''),
                                        getattr(self, '_login_device', ''),
                                        getattr(self, '_login_p', '')
                                    )
                            elif self._servers:
                                # 尝试用正确的 LineId 重新进房
                                await asyncio.sleep(0.5)
                                await self.send({"RoomId": jump_room, "Password": "", "LineId": int(jump_line), "c": "JoinRoom"})
                        else:
                            self._join_fail_count += 1

                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    self._log(f"⚠ 连接关闭: {e}")
                    if not self.running:
                        break
                    self._log("⏳ 尝试重连...")
                    await asyncio.sleep(3)
                    if await self.connect():
                        self._log("✓ 重连成功，重新登录...")
                        await self.login(
                            getattr(self, '_login_token', ''),
                            getattr(self, '_login_device', ''),
                            getattr(self, '_login_p', '')
                        )
                    else:
                        await asyncio.sleep(3)

        async def input_loop():
            """接收用户输入"""
            loop = asyncio.get_event_loop()
            while self.running:
                try:
                    line = await loop.run_in_executor(None, input, "")
                    if not self.running:
                        break
                    if line.strip() == "":
                        # 空行发送心跳
                        await self.send_raw("p")
                        self._log("→ p (心跳)")
                    elif line.startswith("{"):
                        # JSON 格式直接发送
                        try:
                            data = json.loads(line)
                            await self.send(data)
                        except json.JSONDecodeError:
                            await self.send_raw(line)
                            self._log(f"→ {line}")
                    elif line.startswith("查周榜") or line.startswith("查月榜"):
                        # 处理排行榜查询
                        await self.handle_rank_query(line)
                    elif line.startswith("查房"):
                        # 处理查房
                        match = re.search(r'查房(\d+)', line)
                        if match:
                            await self.handle_room_query(match.group(1))
                    elif line.startswith("总结喇叭") or line.startswith("喇叭总结"):
                        # 处理总结喇叭
                        await self.handle_ai_summary(line)
                    elif line.startswith("固定房间"):
                        # 处理固定房间
                        match = re.search(r'固定房间\s*(\d+)', line)
                        if match:
                            room_id = match.group(1)
                            self.set_fixed_room(room_id)
                            print(f"已设置固定房间: {room_id}")
                    elif "取消固定" in line:
                        self.clear_fixed_room()
                        print("已取消固定房间")
                    elif line.startswith("自动跟随"):
                        match = re.search(r'自动跟随\s*(\d+)', line)
                        if match:
                            sid = match.group(1)
                            await self.set_auto_follow(sid)
                            print(f"已设置自动跟随: {sid}")
                    elif "取消跟随" in line:
                        self.clear_auto_follow()
                        self._current_followed_room = ""
                        print("已取消自动跟随")
                    elif "开启自动换位" in line:
                        await self.toggle_auto_change_site(True)
                        print(f"自动换位: {'开启' if self._auto_change_site else '关闭'}")
                    elif "关闭自动换位" in line:
                        await self.toggle_auto_change_site(False)
                        print(f"自动换位: {'开启' if self._auto_change_site else '关闭'}")
                    elif line.startswith("跟随语"):
                        msg_content = line[3:].strip()
                        if msg_content:
                            self.set_follow_message(msg_content)
                            print(f"已设置跟随语: {msg_content}")
                        else:
                            current_msg = self.get_follow_message()
                            print(f"当前跟随语: {current_msg if current_msg else '未设置'}")
                    elif "破解" in line:
                        match = re.search(r'破解\s*(\d+)', line)
                        if match:
                            asyncio.create_task(self.handle_room_crack(match.group(1)))
                    else:
                        # 字符串原样发送
                        await self.send_raw(line)
                        self._log(f"→ {line}")
                except EOFError:
                    break

        await asyncio.gather(recv_loop(), input_loop())

    def _t(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    async def handle_chat_history(self, count: int = 10):
        """处理聊天记录请求，直接输出最近N条房间消息"""
        self._log(f"处理聊天记录请求: 最近{count}条")

        # 防刷：检查是否在10秒内重复请求
        now = time.time()
        if now - self._last_summary_time < 5:
            await self.send_msg(f"操作太频繁，请{int(5 - (now - self._last_summary_time))}秒后再试", "#FFA500")
            return
        self._last_summary_time = now

        messages = self._read_recent_room_messages_by_count(count)
        self._log(f"读取到{len(messages)}条房间消息")

        if not messages:
            await self.send_msg("暂无聊天记录", "#FFA500")
            return

        await self.send_msg(f"【最近{len(messages)}条聊天记录】", "#FFFF00")
        await asyncio.sleep(0.5)

        # 每条消息分段发送，格式：时间 玩家名：内容
        for msg in messages:
            timestamp = msg["timestamp"]
            username = msg["userName"]
            content = msg["msg"]
            msg_text = f"{timestamp} {username}：{content}"

            # 如果消息过长，分段发送
            max_len = 80
            if len(msg_text) <= max_len:
                await self.send_msg(msg_text, "#00FFFF")
            else:
                # 分段发送
                for i in range(0, len(msg_text), max_len):
                    part = msg_text[i:i + max_len]
                    await self.send_msg(part, "#00FFFF")
            await asyncio.sleep(1.5)

    async def handle_room_summary(self, minutes: int = 5):
        """处理总结房间消息请求"""
        self._log(f"处理总结房间请求 (最近{minutes}分钟)")

        # 防刷：检查是否在10秒内重复请求
        now = time.time()
        if now - self._last_summary_time < 10:
            await self.send_msg(f"操作太频繁，请{int(10 - (now - self._last_summary_time))}秒后再试", "#FFA500")
            return
        self._last_summary_time = now

        messages = self._read_recent_room_messages(minutes)
        self._log(f"读取到{len(messages)}条房间消息")

        if not messages:
            await self.send_msg(f"最近{minutes}分钟暂无房间消息", "#FFA500")
            return

        await self.send_msg(f"正在总结最近{minutes}分钟的{len(messages)}条消息...", "#00FF00")

        summary = self.ai_summarizer.summarize_room_messages(messages, minutes)

        max_len = 100
        for i in range(0, len(summary), max_len):
            part = summary[i:i + max_len]
            await self.send_msg(part, "#00FFFF")
            await asyncio.sleep(1.5)

    def _read_recent_room_messages(self, minutes: int = 5) -> list:
        """从日志文件读取最近N分钟的房间消息"""
        messages = []
        log_file = self.log_path if hasattr(self, 'log_path') else os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    # 匹配房间消息格式: [时间戳] ← RoomSay{"s":14,..."m":"内容"}
                    match = re.match(r'\[(\d{2}:\d{2}:\d{2})\] ← RoomSay', line)
                    if not match:
                        continue

                    timestamp_str = match.group(1)

                    # 解析 RoomSay JSON
                    json_start = line.find("RoomSay{")
                    if json_start == -1:
                        continue
                    json_str = line[json_start + 7:]

                    try:
                        data = json.loads(json_str)
                        site = data.get("s", 0)
                        user_data = data.get("u", [])
                        msg_content = data.get("m", "")

                        if len(user_data) >= 3:
                            username = user_data[2]
                        else:
                            username = "未知玩家"

                        # 过滤掉机器人的消息
                        if username == self._bot_name:
                            continue

                        if msg_content:
                            messages.append({
                                "timestamp": timestamp_str,
                                "site": site,
                                "userName": username,
                                "msg": msg_content
                            })
                    except:
                        continue
        except Exception as e:
            self._log(f"读取房间消息失败: {e}")
            return []

        now = datetime.now()
        current_time_str = now.strftime("%H:%M:%S")
        cutoff_time_str = (now - timedelta(minutes=minutes)).strftime("%H:%M:%S")

        recent_messages = []
        for msg in messages:
            msg_time = msg["timestamp"]
            if cutoff_time_str <= current_time_str:
                if cutoff_time_str <= msg_time <= current_time_str:
                    recent_messages.append(msg)
            else:
                if msg_time >= cutoff_time_str or msg_time <= current_time_str:
                    recent_messages.append(msg)

        return [{"site": m["site"], "userName": m["userName"], "msg": m["msg"]} for m in recent_messages]

    def _read_recent_room_messages_by_count(self, count: int = 10) -> list:
        """从日志文件读取最近N条房间消息（倒序取最新的）"""
        messages = []
        log_file = self.log_path if hasattr(self, 'log_path') else os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    # 匹配房间消息格式: [时间戳] ← RoomSay{"s":14,..."m":"内容"}
                    match = re.match(r'\[(\d{2}:\d{2}:\d{2})\] ← RoomSay', line)
                    if not match:
                        continue

                    timestamp_str = match.group(1)

                    # 解析 RoomSay JSON
                    json_start = line.find("RoomSay{")
                    if json_start == -1:
                        continue
                    json_str = line[json_start + 7:]

                    try:
                        data = json.loads(json_str)
                        site = data.get("s", 0)
                        user_data = data.get("u", [])
                        msg_content = data.get("m", "")

                        if len(user_data) >= 3:
                            username = user_data[2]
                        else:
                            username = "未知玩家"

                        # 过滤掉机器人的消息
                        if username == self._bot_name:
                            continue

                        if msg_content:
                            messages.append({
                                "timestamp": timestamp_str,
                                "site": site,
                                "userName": username,
                                "msg": msg_content
                            })
                    except:
                        continue
        except Exception as e:
            self._log(f"读取房间消息失败: {e}")
            return []

        # 取最新的N条消息（从文件末尾取）
        return [{"timestamp": m["timestamp"], "site": m["site"], "userName": m["userName"], "msg": m["msg"]} for m in messages[-count:]]

    async def _query_room_on_current_connection(self, room_id: str):
        """用当前连接查询玩家列表（不查房间信息）"""
        self._log(f"用当前连接查询房间: {room_id}")

        player_event = asyncio.Event()
        # 使用实例属性存储结果，避免闭包引用问题
        setattr(self, f'_query_result_{room_id}', [])

        def make_handler():
            def handler(msg):
                parsed = self._parse_room_sync(msg)
                setattr(self, f'_query_result_{room_id}', parsed.get("players", []))
                player_event.set()
            return handler

        self._player_query_handlers[room_id] = make_handler()

        try:
            query_player = json.dumps({"c": "SO_o", "n": f"Player{room_id}"})
            self._log(f"→ 当前连接发送 Player 查询: {query_player}")
            await self.ws.send(query_player)

            try:
                await asyncio.wait_for(player_event.wait(), timeout=5.0)
                players = getattr(self, f'_query_result_{room_id}', [])
                self._log(f"✓ 当前连接查房完成: players={len(players)}")
                # 清理
                delattr(self, f'_query_result_{room_id}')
                return {"players": players, "server": "current"}
            except asyncio.TimeoutError:
                players = getattr(self, f'_query_result_{room_id}', [])
                self._log(f"⏰ 当前连接查房超时: players={len(players)}")
                # 清理
                if hasattr(self, f'_query_result_{room_id}'):
                    delattr(self, f'_query_result_{room_id}')
                return {"players": players, "server": "current"}
        except Exception as e:
            self._log(f"→ 当前连接查房失败: {type(e).__name__}: {e}")
            return {"players": [], "server": "current", "error": str(e)}
        finally:
            # 确保清理
            if hasattr(self, f'_query_result_{room_id}'):
                delattr(self, f'_query_result_{room_id}')

    async def _query_room_on_server(self, ws_url: str, http_url: str, room_id: str, token: str, device: str, p: str) -> dict:
        """在单个服务器上查询房间，返回结果或None"""
        self._log(f"[{ws_url}] 开始查房: room={room_id}, token={token[:10] if token else 'empty'}...")
        try:
            async with websockets.connect(ws_url, additional_headers={"Origin": http_url}) as ws:
                # 登录
                login_msg = json.dumps({"i": token, "device": device, "p": p})
                await ws.send(login_msg)
                
                # 等待登录成功
                for _ in range(10):
                    try:
                        resp = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        if "Login" in resp:
                            break
                    except asyncio.TimeoutError:
                        continue
                
                # 只查询 UserInfo，不 JoinHall，避免挤掉当前连接
                await ws.send(json.dumps({"c": "UserInfo"}))
                await asyncio.sleep(0.3)
                
                # 查询玩家
                player_event = asyncio.Event()
                result = {"players": [], "server": ws_url}

                async def listener():
                    try:
                        while not player_event.is_set():
                            try:
                                resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                                if f'"n":"Player{room_id}"' in resp:
                                    self._log(f"← {ws_url} 收到: {resp[:200]}...")
                                    result["players"] = self._parse_room_sync(resp).get("players", [])
                                    player_event.set()
                            except asyncio.TimeoutError:
                                if player_event.is_set():
                                    break
                    except:
                        pass

                listener_task = asyncio.create_task(listener())

                # 短暂等待确保 listener 开始
                await asyncio.sleep(0.1)

                # 发送查询
                self._log(f"→ {ws_url} 发送 Player 查询...")
                try:
                    query_player = json.dumps({"c": "SO_o", "n": f"Player{room_id}"})
                    await ws.send(query_player)
                    self._log(f"→ {ws_url} 发送 Player 成功")
                except Exception as e:
                    self._log(f"→ {ws_url} 发送失败: {type(e).__name__}: {e}")
                    listener_task.cancel()
                    return {"players": [], "server": ws_url, "error": str(e)}

                # 等待响应，最多5秒
                try:
                    await asyncio.wait_for(player_event.wait(), timeout=5.0)
                    self._log(f"✓ {ws_url} 查房完成: players={len(result.get('players', []))}")
                except asyncio.TimeoutError:
                    self._log(f"⏰ {ws_url} 查房超时: players={len(result.get('players', []))}")

                listener_task.cancel()
                return result

        except Exception as e:
            return {"players": [], "server": ws_url, "error": str(e)}

    async def handle_room_query(self, room_id: str):
        """处理查房请求 - 先用当前连接，失败则顺序查其他服务器"""
        self._log(f"处理查房请求: {room_id}")

        # 记录当前房间，查完后要回到这里
        current_room = self._current_followed_room or self.get_fixed_room()

        # 获取登录信息
        token = getattr(self, '_login_token', '')
        device = getattr(self, '_login_device', '')
        p = getattr(self, '_login_p', '')

        if not token:
            await self.send_msg("查房失败：未登录", "#FF0000")
            return

        result = None
        success = False
        used_backup_server = False

        # 1. 先尝试用当前连接直接发送查询
        if self.ws:
            self._log(f"用当前连接查询: {self.ws}")
            try:
                result = await self._query_room_on_current_connection(room_id)
                if result.get("players"):
                    success = True
                    self._log(f"当前连接查房成功")
                else:
                    self._log(f"当前连接查不到，尝试备用服务器...")
            except Exception as e:
                self._log(f"当前连接查询失败: {e}")

        # 2. 如果当前连接失败，顺序查其他服务器
        if not success and self._servers:
            for i, (ws_url, http_url) in enumerate(self._servers):
                if i == self._current_server_index:
                    continue  # 跳过当前连接
                self._log(f"尝试服务器: {ws_url}")
                try:
                    result = await self._query_room_on_server(ws_url, http_url, room_id, token, device, p)
                    if result.get("players"):
                        success = True
                        used_backup_server = True
                        self._log(f"查房成功: {ws_url}")
                        break
                except Exception as e:
                    self._log(f"服务器{ws_url}查询失败: {e}")
                    continue

        # 3. 如果用了备用服务器，连接可能被挤掉，需要回到原来房间
        if used_backup_server and current_room:
            self._log("等待重连完成...")
            await asyncio.sleep(3)  # 等待自动重连
            # 验证连接是否恢复
            retry_count = 0
            while retry_count < 10:
                try:
                    if self.ws:
                        # 尝试发送一个测试消息
                        await asyncio.wait_for(self.ws.send('{"c":"UserInfo"}'), timeout=2.0)
                        self._log("连接已恢复")
                        break
                except:
                    retry_count += 1
                    self._log(f"等待连接恢复... ({retry_count}/10)")
                    await asyncio.sleep(1)
            else:
                self._log("重连超时，强制重连...")
                if await self.connect():
                    self._log("强制重连成功，重新登录...")
                    await self.login(token, device, p)

            # 回到原来房间
            if self.ws:
                self._log(f"查房完成，回到房间: {current_room}")
                await self.send({"RoomId": current_room, "Password": "", "c": "JoinRoom"})
                await asyncio.sleep(1.5)  # 等待进入房间完成

        # 4. 回复结果
        if success and result:
            players = result.get("players", [])
            if players:
                sorted_players = sorted(players, key=lambda pl: pl.get('RoomSite', 999))
                player_list = [f"{pl['RoomSite']}:{pl['UserName']}" for pl in sorted_players]
                msg = f"房间{room_id}玩家：" + "，".join(player_list)
                try:
                    await self.send_msg(msg, "#00FF00")
                except Exception as e:
                    self._log(f"回复查房结果失败: {e}")
            else:
                try:
                    await self.send_msg("玩家信息获取失败", "#FF0000")
                except Exception as e:
                    self._log(f"回复查房失败: {e}")
        else:
            self._log(f"查房失败：所有服务器都无数据")
            try:
                await self.send_msg(f"房间{room_id}查房失败", "#FF0000")
            except Exception as e:
                self._log(f"回复查房失败: {e}")

    def _parse_room_sync(self, msg: str) -> dict:
        """解析 SO_Sync 消息中的房间/玩家信息"""
        result = {}

        # 用正则解析（和自动换位一样的逻辑）
        if "Player" in msg:
            # 解析玩家列表
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
            # 解析房间字段（用JSON解析，key可能是字符串或整数）
            try:
                data = json.loads(msg)
                for item in data.get("l", []):
                    if len(item) >= 3 and item[0] == 1:
                        key = str(item[1])
                        value = item[2]
                        result[key] = value
            except Exception:
                pass

        n_match = re.search(r'"n":"([^"]+)"', msg)
        if n_match:
            result["n"] = n_match.group(1)

        return result

    def close_log(self):
        """关闭日志文件"""
        if self.log_file:
            self.log_file.close()


async def main():
    # 服务器列表（按优先级）
    servers = [
        ("wss://kg3.ss911.cn:6103/", "https://t1.ss911.cn"),
        ("wss://kg2.ss911.cn:6102/", "https://t1.ss911.cn"),
        ("wss://kg4.ss911.cn:6104/", "https://t1.ss911.cn"),
        ("wss://kg1.ss911.cn:6101/", "https://t1.ss911.cn"),
    ]
    
    bot = None
    connected = False
    
    # 尝试连接每个服务器
    for ws_url, http_url in servers:
        print(f"尝试连接: {ws_url}")
        bot = GameBot(ws_url, http_url)
        bot._open_log()
        
        # 登录参数
        login_token = "+NemHgNs1Fr0wV8slM6jSbBDDmmWEV6H"
        login_device = "html5:1461"
        login_p = "VzG6JI4TXVgkroND+wq1kA=="
        
        # 保存服务器信息
        bot._servers = servers
        bot._current_server_index = servers.index((ws_url, http_url))
        
        # 显示固定房间配置
        fixed_room = bot.get_fixed_room()
        if fixed_room:
            print(f"固定房间: {fixed_room}")
        
        # 显示自动跟随配置
        auto_follow_sid = bot.get_auto_follow_sid()
        if auto_follow_sid:
            auto_follow_user_id = bot.get_auto_follow_user_id()
            print(f"自动跟随: sid={auto_follow_sid}, userId={auto_follow_user_id}")
        
        if await bot.connect():
            print(f"成功连接到: {ws_url}")
            connected = True
            await bot.login(login_token, login_device, login_p)
            
            # 保存登录参数供重连使用
            bot._login_token = login_token
            bot._login_device = login_device
            bot._login_p = login_p
            
            await bot.run()
            break
        else:
            print(f"连接失败: {ws_url}")
            bot.close_log()
            bot = None
    
    if not connected:
        print("所有服务器连接失败")
    
    if bot:
        bot.close_log()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止")
