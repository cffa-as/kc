"""排行榜处理器"""

import asyncio
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import GameBot


class RankHandler:
    """排行榜处理器"""

    TYPE_NAMES = {
        "week": "周榜", "week2": "周榜2",
        "month": "月榜", "month2": "月榜2",
        "year": "年榜", "year2": "年榜2"
    }

    def __init__(self, bot: "GameBot"):
        self.bot = bot

    async def handle_rank_query(self, content: str):
        rank_type_map = {
            "查周榜2": ("week2", "周榜2"), "查月榜2": ("month2", "月榜2"),
            "查年榜2": ("year2", "年榜2"), "查周榜": ("week", "周榜"),
            "查月榜": ("month", "月榜"), "查年榜": ("year", "年榜"),
        }

        # 全榜查询
        if content.strip() in {"查月榜", "查周榜", "查年榜"}:
            rank_type = {"查月榜": "month", "查周榜": "week", "查年榜": "year"}[content.strip()]
            await self._handle_all_tools_rank(rank_type)
            return

        # 范围查询: 查周榜2-8
        if range_match := re.search(r'查(周|月|年)榜(\d+)-(\d+)', content):
            rank_type = {"周": "week", "月": "month", "年": "year"}[range_match.group(1)]
            await self._handle_all_tools_rank(rank_type, int(range_match.group(2)), int(range_match.group(3)))
            return

        # 精确匹配命令
        for cmd, (rank_type, type_name) in rank_type_map.items():
            if cmd in content:
                if match := re.search(rf'{cmd}\s*(.+)', content):
                    result = self._query_single_tool(match.group(1).strip(), rank_type)
                    if not result:
                        await self.bot.send_msg(f"暂无{match.group(1).strip()}的{type_name}数据", "#FF0000")
                    else:
                        await self._send_tool_result(*result)
                else:
                    await self._handle_all_tools_rank(rank_type)
                return

        # 单道具查询 - 自动尝试2榜
        if "查月榜" in content:
            rank_type, rank_type2, type_str = "month", "month2", "月"
        elif "查周榜" in content:
            rank_type, rank_type2, type_str = "week", "week2", "周"
        else:
            return

        if not (match := re.search(rf'查{type_str}榜\s*(.+)', content)):
            return

        tool_name = match.group(1).strip()
        result = self._query_single_tool(tool_name, rank_type)

        if not result:
            type_name2 = f"{type_str}榜2"
            result = self._query_single_tool(tool_name, rank_type2)
            if result:
                await self.bot.send_msg(f"{tool_name}在{type_name2}有数据:", "#00FF00")
            else:
                await self.bot.send_msg(f"暂无{tool_name}的{type_str}榜和{type_str}榜2数据", "#FF0000")
                return

        await self._send_tool_result(*result)

    def _query_single_tool(self, tool_name: str, rank_type: str):
        results, price = self.bot.rank_query.query_rank(tool_name, rank_type)
        return (results, price) if results else None

    async def _handle_all_tools_rank(self, rank_type: str, start_rank: int = 1, end_rank: int = 30):
        type_name = self.TYPE_NAMES.get(rank_type, "周榜")
        await self.bot.send_msg(f"正在查询{type_name}...", "#00FF00")

        results = self.bot.rank_query.query_all_tools_rank(rank_type)
        if not results:
            await self.bot.send_msg(f"暂无{type_name}数据", "#FF0000")
            return

        header = f"【本{type_name}道具榜】"
        if start_rank != 1 or end_rank != 30:
            header = f"【本{type_name}道具榜 第{start_rank}-{end_rank}名】"
        await self.bot.send_msg(header, "#FFFF00")
        await asyncio.sleep(1.5)

        filtered = [r for r in results if start_rank <= r[0] <= end_rank]
        if not filtered:
            await self.bot.send_msg(f"暂无第{start_rank}-{end_rank}名数据", "#FF0000")
            return

        for rank, username, tool_name, num, total_price in filtered:
            await self.bot.send_msg(f"{rank}. {username}: {tool_name} {num} 总守护:{int(total_price)}")
            await asyncio.sleep(1.5)

    async def _send_tool_result(self, results: list, price: float):
        for item in results:
            await self.bot.send_msg(f"{item['userName']}: {item['num']} 总守护:{int(item['num'] * price)}")
            await asyncio.sleep(1.5)
