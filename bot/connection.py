"""连接管理模块"""

import asyncio
import json
import time
from typing import Optional

import websockets


class Connection:
    """WebSocket连接管理"""

    def __init__(self, url: str, origin: str = "https://t1.ss911.cn"):
        self.url = url
        self.origin = origin
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self._last_heartbeat = time.time()
        self._user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    async def connect(self) -> bool:
        """连接服务器"""
        try:
            self.ws = await websockets.connect(
                self.url,
                origin=self.origin,
                user_agent_header=self._user_agent
            )
            self.running = True
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        self.running = False
        if self.ws:
            await self.ws.close()

    async def send(self, data: dict, censor: callable = None) -> bool:
        """发送JSON数据"""
        if not self.ws:
            return False

        if censor and data.get("c") == "SayInRoom" and "Msg" in data:
            data["Msg"] = censor(data["Msg"])

        try:
            msg = json.dumps(data, ensure_ascii=False)
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def send_raw(self, msg: str) -> bool:
        """发送原始字符串"""
        if not self.ws:
            return False
        try:
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def recv(self, timeout: float = 1.0) -> Optional[str]:
        """接收消息"""
        if not self.ws:
            return None
        try:
            return await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except websockets.exceptions.ConnectionClosed:
            self.running = False
            return None

    async def heartbeat(self, interval: int = 30):
        """自动心跳"""
        while self.running:
            now = time.time()
            if now - self._last_heartbeat >= interval:
                self._last_heartbeat = now
                await self.send_raw("p")
            await asyncio.sleep(1)
