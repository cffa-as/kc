"""排行榜查询模块"""

import json
import os
import requests
from typing import Optional


class RankQuery:
    """排行榜查询工具"""

    BASE_URL = "https://t1.ss911.cn/Rank/GetToolRank.ss"
    COOKIE = "JSESSIONID=F9257055C5772AB3E8712872FF04674F; Hm_lvt_8db5877631f6b3e1e50b3a82695c5484=1777547687,1777731807,1778506341,1778936394; HMACCOUNT=410244466E960FFE; UserId=126521216; UserName=14705896759; UserPwd=3115e599ad5a97c0; uservalues=ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D; LastLogin=2026-05-16~21:00:05; yzmCode=wcvqGqJhW68Z8trn%2B184%2BBOWb59LRIeZ; Hm_lpvt_8db5877631f6b3e1e50b3a82695c5484"
    USER_HASH = "ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D"

    def __init__(self):
        self.headers = {"Cookie": self.COOKIE}
        self.tool_data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "道具完整数据.json")
        self.tool_data = {}
        self._load_tool_data()

    def _load_tool_data(self):
        """加载道具完整数据"""
        try:
            if os.path.exists(self.tool_data_file):
                with open(self.tool_data_file, "r", encoding="utf-8") as f:
                    self.tool_data = json.load(f)
        except Exception:
            self.tool_data = {}

    def _save_tool_data(self):
        """保存道具完整数据"""
        with open(self.tool_data_file, "w", encoding="utf-8") as f:
            json.dump(self.tool_data, f, ensure_ascii=False, indent=2)

    def get_tool_price(self, name: str) -> float:
        """获取道具守护值"""
        return self.tool_data.get(name, {}).get("price", 0.0)

    def update_tool_objid(self, name: str, objid: str):
        """更新道具objid"""
        if name in self.tool_data and self.tool_data[name].get("objid", "0") == "0":
            self.tool_data[name]["objid"] = objid
            self._save_tool_data()
            print(f"[更新] {name} objid -> {objid}")

    def get_tool_id(self, name: str) -> Optional[str]:
        """获取道具ID（精确匹配 + 模糊匹配）"""
        if name in self.tool_data:
            objid = self.tool_data[name].get("objid", "")
            if objid and objid != "0":
                return objid

        for tool_name, tool_info in self.tool_data.items():
            objid = tool_info.get("objid", "")
            if objid and objid != "0":
                if name in tool_name or tool_name in name:
                    return objid
        return None

    def _build_params(self, tool_id: str = None, rank_type: str = "week") -> dict:
        """构建请求参数"""
        h_value = "0" if rank_type == "week" else "2"
        params = {
            "h": h_value,
            "g": "0",
            "n": "3",
            "p": "1",
            "u": self.USER_HASH
        }
        if tool_id:
            params["toolid"] = tool_id
        return params

    def _fetch(self, params: dict) -> dict:
        """发送请求"""
        try:
            resp = requests.get(self.BASE_URL, params=params, headers=self.headers, timeout=10)
            return resp.json()
        except Exception as e:
            print(f"请求失败: {e}")
            return {}

    def _parse_rank_list(self, data: dict) -> list:
        """解析排行榜数据"""
        results = []
        if "rankList" in data:
            for item in data["rankList"]:
                results.append({
                    "userName": item.get("userName", ""),
                    "num": item.get("num", 0)
                })
        return results

    def _parse_tool_list(self, data: dict) -> list:
        """解析道具列表"""
        tools = []
        if "rankList" in data:
            for item in data["rankList"]:
                objname = item.get("objname", "")
                objid = str(item.get("objid", ""))
                if objname and objid:
                    tools.append({"name": objname, "id": objid})
                    self.update_tool_objid(objname, objid)
        return tools

    def fetch_tool_list(self, rank_type: str = "week") -> bool:
        """获取道具列表"""
        params = self._build_params(rank_type=rank_type)
        data = self._fetch(params)
        if "rankList" in data:
            self._parse_tool_list(data)
            return True
        return False

    def fetch_all_tools(self, rank_type: str = "week") -> list:
        """获取所有道具列表"""
        params = self._build_params(rank_type=rank_type)
        data = self._fetch(params)
        return self._parse_tool_list(data)

    def query_player_tools(self, tool_id: str, tool_name: str, rank_type: str = "week") -> list:
        """查询指定道具的玩家排行榜"""
        data = self._fetch(self._build_params(tool_id, rank_type))
        return self._parse_rank_list(data)

    def query_rank(self, tool_name: str, rank_type: str = "week") -> tuple:
        """查询道具排行榜"""
        tool_id = self.get_tool_id(tool_name)
        if not tool_id:
            self.fetch_tool_list(rank_type)
            tool_id = self.get_tool_id(tool_name)
            if not tool_id:
                return None, 0.0

        price = self.get_tool_price(tool_name)
        self.update_tool_objid(tool_name, tool_id)
        results = self._parse_rank_list(self._fetch(self._build_params(tool_id, rank_type)))
        return results, price

    def query_all_tools_rank(self, rank_type: str = "week") -> list:
        """查询所有道具排行榜整合"""
        tools = self.fetch_all_tools(rank_type)
        if not tools:
            return []

        tool_best_player = {}

        for tool in tools:
            tool_name = tool["name"]
            tool_id = tool["id"]
            price = self.get_tool_price(tool_name)
            players = self.query_player_tools(tool_id, tool_name, rank_type)

            for player in players:
                username = player["userName"]
                num = player["num"]
                if tool_name not in tool_best_player or num > tool_best_player[tool_name][1]:
                    tool_best_player[tool_name] = (username, num, price)

        results = []
        for tool_name, (username, num, price) in tool_best_player.items():
            results.append((username, tool_name, num, num * price))

        results.sort(key=lambda x: x[3], reverse=True)
        return [(i + 1, *r) for i, r in enumerate(results)]
