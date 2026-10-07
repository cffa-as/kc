"""交易查询处理器"""

import asyncio
import json
import os
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional
import aiohttp

from config import get_u_param

if TYPE_CHECKING:
    from ..core import GameBot


class TradeHandler:
    """交易查询处理器"""

    TRADE_LOOKBACK_DAYS = 60
    TREND_PREVIEW_LIMIT = 12

    SEARCH_API = (
        "https://t1.ss911.cn/Shop/Search2025.ss"
        "?p={page}&ps=40&s={query}&u={u}"
    )

    GOODS_SEARCH_API = (
        "https://t1.ss911.cn/Trade/GoodsSearch.ss"
        "?gn={gn}&p=1&ps=40&o=3&u={u}"
    )

    COLOR_API = (
        "https://t1.ss911.cn/UserGoods/ChangeColorView.ss"
        "?group={colorgroup}&u={u}"
    )

    TRADE_API_TEMPLATE = (
        "https://t1.ss911.cn/Trade/History.ss"
        "?page={page}&pageSiz=10&objtype={objtype}&objid={objid}&u={u}"
    )

    def __init__(self, bot: "GameBot"):
        self.bot = bot
        self._cache_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "trade_cache.json"
        )
        self._cache: dict[str, dict] = {}
        self._load_cache()

    @staticmethod
    def _u_param() -> str:
        return get_u_param()

    def _create_session(self):
        """创建使用系统 CA 校验的 aiohttp 会话。"""
        return aiohttp.ClientSession()

    @asynccontextmanager
    async def _session_scope(self, session=None):
        if session is not None:
            yield session
            return
        async with self._create_session() as owned_session:
            yield owned_session

    def _load_cache(self):
        """加载缓存"""
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
        except Exception:
            self._cache = {}

    def _save_cache(self):
        """保存缓存"""
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.bot._log(f"保存交易缓存失败: {e}")

    def _upsert_cache(self, objid: str, name: str, objtype: Optional[int],
                      colorgroup: Optional[int] = None, colorname: Optional[str] = None,
                      color_ids: Optional[dict] = None):
        """更新缓存，objid为主键，存储name/objtype/colorgroup/colorname/color_ids"""
        if objid in self._cache:
            updated = False
            if self._cache[objid]["name"] != name:
                self._cache[objid]["name"] = name
                updated = True
            if objtype is not None and self._cache[objid].get("objtype") != objtype:
                self._cache[objid]["objtype"] = objtype
                updated = True
            existing_cg = self._cache[objid].get("colorgroup")
            if colorgroup is not None and existing_cg != colorgroup:
                self._cache[objid]["colorgroup"] = colorgroup
                updated = True
            existing_cn = self._cache[objid].get("colorname")
            if colorname is not None and existing_cn != colorname:
                self._cache[objid]["colorname"] = colorname
                updated = True
            existing_ci = self._cache[objid].get("color_ids")
            if color_ids is not None and existing_ci != color_ids:
                self._cache[objid]["color_ids"] = color_ids
                updated = True
            if updated:
                self._save_cache()
        else:
            entry = {"name": name}
            if objtype is not None:
                entry["objtype"] = objtype
            if colorgroup is not None:
                entry["colorgroup"] = colorgroup
            if colorname is not None:
                entry["colorname"] = colorname
            if color_ids is not None:
                entry["color_ids"] = color_ids
            self._cache[objid] = entry
            self._save_cache()

    def find_ids_by_name(self, name: str) -> list[str]:
        """通过名称模糊查找所有匹配的objid"""
        name_lower = name.lower()
        return [
            objid for objid, info in self._cache.items()
            if name_lower in info["name"].lower()
        ]

    def find_id_by_name(self, name: str) -> Optional[str]:
        """通过名称模糊查找objid（兼容旧接口）"""
        ids = self.find_ids_by_name(name)
        return ids[0] if ids else None

    def list_cache(self) -> list[dict]:
        """返回所有缓存的物品信息列表"""
        return [
            {
                "objid": objid,
                "name": info["name"],
                "objtype": info.get("objtype", 2),
                "colorgroup": info.get("colorgroup"),
                "colorname": info.get("colorname"),
                "color_ids": info.get("color_ids"),
            }
            for objid, info in self._cache.items()
        ]

    async def _goods_search_api(self, query: str, session=None) -> list[dict]:
        """调用GoodsSearch接口搜索物品（兜底），返回goods列表"""
        url = self.GOODS_SEARCH_API.format(gn=urllib.parse.quote(query), u=self._u_param())
        async with self._session_scope(session) as client:
            try:
                async with client.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
                    data = json.loads(text)
            except Exception as e:
                self.bot._log(f"GoodsSearch接口调用失败: {e}")
                return []

        goods = data.get("goods") or []
        count = data.get("count") or 0
        self.bot._log(f"GoodsSearch「{query}」返回 {count} 条，goods {len(goods)} 条")

        for item in goods:
            objid = str(item.get("objid") or item.get("id") or "")
            objname = item.get("objname", "未知")
            if objid:
                self._upsert_cache(objid, objname, objtype=None)

        return goods

    async def _search_api(self, query: str, page: int = 1, session=None) -> list[dict]:
        """调用Search2025接口搜索物品，支持分页"""
        url = self.SEARCH_API.format(
            page=page,
            query=urllib.parse.quote(query),
            u=self._u_param(),
        )
        async with self._session_scope(session) as client:
            try:
                async with client.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
                    data = json.loads(text)
            except Exception as e:
                self.bot._log(f"Search2025接口调用失败: {e}")
                return []

        goods = data.get("goods") or []
        count = data.get("count") or 0
        self.bot._log(f"Search2025「{query}」第{page}页返回 {count} 条，goods {len(goods)} 条")

        if not goods:
            self.bot._log(f"Search2025无结果，尝试GoodsSearch兜底...")
            return await self._goods_search_api(query, session)

        for item in goods:
            objid = str(item.get("id") or item.get("objid") or "")
            objname = item.get("name", "未知")
            colorgroup = item.get("colorgroup")
            colorname = item.get("colorname", "未知")
            if objid:
                self._upsert_cache(objid, objname, objtype=None, colorgroup=colorgroup, colorname=colorname)

        return goods

    async def _fetch_color_variants(self, colorgroup: int, session=None) -> dict[str, list[int]]:
        """调用ChangeColorView接口获取颜色变体，返回 {model: [objid, ...], ...}"""
        url = self.COLOR_API.format(colorgroup=colorgroup, u=self._u_param())
        async with self._session_scope(session) as client:
            try:
                async with client.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
                    data = json.loads(text)
            except Exception as e:
                self.bot._log(f"ChangeColorView接口调用失败 group={colorgroup}: {e}")
                return {}

        if data.get("msg") != "OK":
            self.bot._log(f"ChangeColorView返回异常: {data.get('msg')}")
            return {}

        names = data.get("names") or {}
        color_ids = {}
        for model, objid_list in (data.get("goods") or {}).items():
            name_list = names.get(model) or []
            color_ids[model] = {
                str(objid): colorname
                for objid, colorname in zip(objid_list, name_list)
            }

        self.bot._log(f"ChangeColorView group={colorgroup} 返回颜色变体: {color_ids}")
        return color_ids

    def _get_objtype(self, objid: str) -> Optional[int]:
        """获取objid对应的objtype，缓存中没有则返回None"""
        return self._cache.get(objid, {}).get("objtype")

    @staticmethod
    def _parse_trade_time(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(text[:19], fmt)
                except ValueError:
                    continue
        return None

    @classmethod
    def _recent_trade_goods(cls, goods: list[dict], now: datetime | None = None) -> list[dict]:
        cutoff = (now or datetime.now()) - timedelta(days=cls.TRADE_LOOKBACK_DAYS)
        return [
            item for item in goods
            if (parsed := cls._parse_trade_time(item.get("addtime"))) is None or parsed >= cutoff
        ]

    async def query_trade(self, objid: str, page: str = None):
        """查询物品交易历史"""
        page_num = int(page) if page else 1
        objname = self._cache.get(objid, {}).get("name", "未知")
        async with self._create_session() as session:
            goods, count, trend_goods, request_failed = await self._fetch_trade_page(
                objid, page_num, session
            )
        goods = self._recent_trade_goods(goods)

        if not goods and not trend_goods:
            if request_failed:
                await self.bot.send_msg("交易接口请求失败，请稍后重试", "#FF0000")
                return
            await self.bot.send_msg(f"【{objname}】近2个月暂无交易记录", "#FF0000")
            return

        if trend_goods:
            await self._send_trend_summary(objname, trend_goods, page_num)
            await self.bot.message_delay(1.5)

        if not goods:
            await self.bot.send_msg(f"【{objname}】近2个月暂无交易记录", "#FFA500")
            return

        await self.bot.send_msg(f"【{objname}】近2个月交易记录（共{len(goods)}条，第{page_num}页）:", "#FFFF00")
        await self.bot.message_delay(1.5)

        for index, item in enumerate(goods, 1):
            date = item.get("addtime", "")[:19]
            price = item.get("exp_one", 0)
            days = item.get("days", "未知")

            msg = f"{index}. 时间:{date} | 总价:{price} | 有效期:{days}"
            await self.bot.send_msg(msg)
            await self.bot.message_delay(1.5)

    async def _send_trend_summary(self, objname: str, trend_goods: list[dict], page: int):
        """用摘要和最近点位替代几十条历史趋势明细。"""
        if not trend_goods:
            return
        dated = [
            (self._parse_trade_time(item.get("inttime")), item)
            for item in trend_goods
        ]
        dated.sort(key=lambda pair: pair[0] or datetime.min, reverse=True)
        points = [item for _date, item in dated]

        def price_value(item: dict) -> float:
            try:
                return float(item.get("price", 0))
            except (TypeError, ValueError):
                return 0.0

        latest = points[0]
        highest = max(points, key=price_value)
        lowest = min(points, key=price_value)
        parts = [
            f"【{objname}】历史趋势（日均价格，共{len(points)}条记录，第{page}页）",
            f"最新：{latest.get('inttime', '未知')}，日均价:{latest.get('price', 0)}",
            f"最高日均价：{highest.get('inttime', '未知')}，价格:{highest.get('price', 0)}",
            f"最低日均价：{lowest.get('inttime', '未知')}，价格:{lowest.get('price', 0)}",
            f"最近{min(len(points), self.TREND_PREVIEW_LIMIT)}条日均价格记录",
        ]
        parts.extend(
            f"{item.get('inttime', '未知')}：日均价 {item.get('price', 0)}"
            for item in points[:self.TREND_PREVIEW_LIMIT]
        )
        await self.bot.send_msg(" | ".join(parts), "#00BFFF")

    async def _fetch_trade_page(
        self, objid: str, page: int, session=None
    ) -> tuple[list[dict], int, list[dict], bool]:
        """获取单个objid指定页的交易数据，并返回本次请求是否失败。"""
        cached_objtype = self._get_objtype(objid)
        correct_objtype = None
        goods = []
        count = 0
        trend_goods = []
        errors = []
        received_response = False

        if cached_objtype is not None:
            objtypes_to_try = [cached_objtype]
        else:
            objtypes_to_try = [2, 3, 1]

        for objtype in objtypes_to_try:
            url = self.TRADE_API_TEMPLATE.format(
                page=page, objtype=objtype, objid=objid, u=self._u_param()
            )
            async with self._session_scope(session) as client:
                try:
                    async with client.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        text = await resp.text()
                        data = json.loads(text)
                except Exception as e:
                    errors.append(str(e))
                    self.bot._log(f"查询交易失败 objid={objid} objtype={objtype}: {e}")
                    continue

            goods = data.get("goods") or []
            count = data.get("count") or 0
            trend_goods = data.get("trendGoods") or []
            received_response = True

            if count > 0 or goods or trend_goods:
                correct_objtype = objtype
                break

        if correct_objtype is not None and correct_objtype != cached_objtype:
            self._upsert_cache(objid, self._cache.get(objid, {}).get("name", "未知"), correct_objtype)

        for item in goods:
            item["objid"] = objid

        request_failed = bool(errors and not received_response)
        return goods, count, trend_goods, request_failed

    async def _expand_all_ids(self, objids: list[str], session=None) -> list[str]:
        """对objids中每个有colorgroup的物品调用颜色接口，展开所有颜色ID"""
        semaphore = asyncio.Semaphore(4)

        async def expand_one(objid: str) -> list[str]:
            cache_entry = self._cache.get(objid, {})
            colorgroup = cache_entry.get("colorgroup")
            if colorgroup:
                async with semaphore:
                    color_ids = await self._fetch_color_variants(colorgroup, session)
                if color_ids:
                    if cache_entry.get("color_ids") != color_ids:
                        self._upsert_cache(
                            objid, cache_entry.get("name", "未知"),
                            cache_entry.get("objtype"),
                            colorgroup, cache_entry.get("colorname"),
                            color_ids
                        )
                    return [
                        str(color_id)
                        for mapping in color_ids.values()
                        for color_id in mapping
                    ]
            return [objid]

        expanded = await asyncio.gather(*(expand_one(objid) for objid in objids))
        return [color_id for ids in expanded for color_id in ids]

    async def query_by_name(self, name: str, page: str = None):
        """通过名称查询交易，先查缓存，没有则调Search2025接口"""
        page_num = int(page) if page else 1
        objids = self.find_ids_by_name(name)

        async with self._create_session() as session:
            if not objids:
                goods = await self._search_api(name, page_num, session)
                if not goods:
                    await self.bot.send_msg(f"未找到「{name}」", "#FF0000")
                    return
                objids = self.find_ids_by_name(name)
                if not objids:
                    await self.bot.send_msg(f"未找到「{name}」", "#FF0000")
                    return
            else:
                needs_refresh = any(
                    self._cache.get(oid, {}).get("colorgroup") is None
                    for oid in objids
                )
                if needs_refresh:
                    await self._search_api(name, page_num, session)
                    objids = self.find_ids_by_name(name)

            await self.bot.send_msg(f"名称「{name}」匹配 {len(objids)} 个物品，查询颜色...", "#FFFF00")
            await self.bot.message_delay(0.5)

            expanded_ids = await self._expand_all_ids(objids, session)
            unique_ids = list(dict.fromkeys(expanded_ids))

            await self.bot.send_msg(
                f"查询出 {len(unique_ids)} 个颜色，开始聚合查询...",
                "#FFFF00"
            )
            await self.bot.message_delay(0.5)

            semaphore = asyncio.Semaphore(4)

            async def fetch_one(objid: str):
                async with semaphore:
                    return await self._fetch_trade_page(objid, page_num, session)

            fetched = await asyncio.gather(*(fetch_one(objid) for objid in unique_ids))

        all_goods: list[dict] = []
        all_count = 0
        all_trend: list[dict] = []
        request_failures = []
        for objid, (goods, count, trend_goods, request_failed) in zip(unique_ids, fetched):
            all_goods.extend(self._recent_trade_goods(goods))
            all_count = len(all_goods)
            all_trend.extend(trend_goods)
            request_failures.append(request_failed)

        if not all_goods and not all_trend:
            if request_failures and all(request_failures):
                await self.bot.send_msg("交易接口请求失败，请稍后重试", "#FF0000")
                return
            await self.bot.send_msg(f"暂无「{name}」的交易记录", "#FF0000")
            return

        all_goods.sort(key=lambda x: x.get("addtime", ""), reverse=True)

        main_objid = next((oid for oid in unique_ids if self._cache.get(oid, {}).get("colorgroup") is not None), objids[0])
        color_map: dict[str, str] = {}
        color_ids = self._cache.get(main_objid, {}).get("color_ids") or {}
        for mapping in color_ids.values():
            for oid, cname in mapping.items():
                color_map[oid] = cname

        if all_trend:
            await self._send_trend_summary(name, all_trend, page_num)
            await self.bot.message_delay(1.5)

        if not all_goods:
            await self.bot.send_msg(f"【{name}】近2个月暂无交易记录", "#FFA500")
            return

        await self.bot.send_msg(
            f"【{name}】近2个月交易记录（共{all_count}条，第{page_num}页，{len(unique_ids)}个ID）:",
            "#FFFF00"
        )
        await self.bot.message_delay(1.5)

        for index, item in enumerate(all_goods, 1):
            date = item.get("addtime", "")[:19]
            price = item.get("exp_one", 0)
            days = item.get("days", "未知")
            objid_str = item.get("objid", "")
            colorname = color_map.get(objid_str, "默认") or "默认"

            msg = f"{index}. 时间:{date} | 物品:{name} | 颜色:{colorname} | 总价:{price} | 有效期:{days}"
            await self.bot.send_msg(msg)
            await self.bot.message_delay(1.5)
