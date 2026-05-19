"""排行榜处理器"""

import asyncio
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import GameBot


class RankHandler:
    """排行榜处理器"""

    def __init__(self, bot: "GameBot"):
        self.bot = bot

    async def handle_rank_query(self, content: str):
        """处理排行榜查询"""
        rank_type = "week"

        # 范围查询: 查周榜2-8 或 查月榜1-10
        range_match = re.search(r'查(周|月)榜(\d+)-(\d+)', content)
        if range_match:
            rank_type = "month" if range_match.group(1) == "月" else "week"
            start_rank = int(range_match.group(2))
            end_rank = int(range_match.group(3))
            await self._handle_all_tools_rank(rank_type, start_rank, end_rank)
            return

        # 全榜查询
        if "查月榜" in content and content.strip() in ["查月榜", "查月榜 "]:
            await self._handle_all_tools_rank("month")
            return
        elif content.strip() in ["查周榜", "查周榜 "]:
            await self._handle_all_tools_rank("week")
            return

        # 单道具查询
        if "查月榜" in content:
            rank_type = "month"
            match = re.search(r'查月榜\s*(.+)', content)
        else:
            match = re.search(r'查周榜\s*(.+)', content)

        if not match:
            return

        tool_name = match.group(1).strip()
        results, price = self.bot.rank_query.query_rank(tool_name, rank_type)

        if results is None:
            await self.bot.send_msg("未找到该道具，请稍后再试", "#FF0000")
            return

        if not results:
            await self.bot.send_msg(f"暂无{tool_name}的{'月' if rank_type == 'month' else '周'}榜数据", "#FF0000")
            return

        for item in results:
            num = item['num']
            total_price = num * price
            msg_text = f"{item['userName']}: {num} 总守护:{int(total_price)}"
            await self.bot.send_msg(msg_text)
            await asyncio.sleep(1.5)

    async def _handle_all_tools_rank(self, rank_type: str, start_rank: int = 1, end_rank: int = 30):
        """处理查询所有道具排行榜"""
        await self.bot.send_msg(f"正在查询{'月' if rank_type == 'month' else '周'}榜...", "#00FF00")

        results = self.bot.rank_query.query_all_tools_rank(rank_type)
        if not results:
            await self.bot.send_msg(f"暂无{'月' if rank_type == 'month' else '周'}榜数据", "#FF0000")
            return

        header = f"【{'本' if rank_type == 'week' else '本'}月道具榜】"
        if start_rank != 1 or end_rank != 30:
            header = f"【{'本' if rank_type == 'week' else '本'}月道具榜 第{start_rank}-{end_rank}名】"
        await self.bot.send_msg(header, "#FFFF00")
        await asyncio.sleep(1.5)

        filtered_results = [item for item in results if start_rank <= item[0] <= end_rank]

        if not filtered_results:
            await self.bot.send_msg(f"暂无第{start_rank}-{end_rank}名数据", "#FF0000")
            return

        for rank, username, tool_name, num, total_price in filtered_results:
            msg_text = f"{rank}. {username}: {tool_name} {num} 总守护:{int(total_price)}"
            await self.bot.send_msg(msg_text)
            await asyncio.sleep(1.5)
