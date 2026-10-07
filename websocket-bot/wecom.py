"""Enterprise WeChat smart-bot bridge."""

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Awaitable, Callable


APP_DIR = Path(__file__).resolve().parent
BRIDGE_SCRIPT = APP_DIR / "wecom_bridge.js"


def normalize_wecom_command(content: str, chat_type: str) -> str:
    """Remove the leading bot mention included in group callbacks."""
    text = str(content or "").strip()
    if chat_type == "group":
        text = re.sub(r"^@\S+\s*", "", text, count=1)
    return text.strip()


def split_wecom_reply(messages: list[str], limit: int = 3000) -> list[str]:
    """Combine game-style reply lines into a few WeCom-safe messages."""
    lines = []
    for message in messages:
        # Game-room replies use pipes because that client cannot render newlines.
        wecom_text = str(message).replace("|", "\n").replace("｜", "\n")
        lines.extend(line.strip() for line in wecom_text.splitlines() if line.strip())
    # WeCom renders Markdown; a plain newline is often collapsed by the client.
    text = "  \n".join(lines)
    if not text:
        return []
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        chunks.append(text[:split_at].rstrip())
        text = text[split_at + 1:].lstrip(" \n")
    return chunks


class WeComBridge:
    """Run the official WeCom Node SDK and exchange JSON lines with Python."""

    def __init__(
        self,
        bot_id: str,
        secret: str,
        on_message: Callable[[dict], Awaitable[None]],
        log: Callable[[str], None],
    ):
        self.bot_id = bot_id
        self.secret = secret
        self.on_message = on_message
        self.log = log
        self.process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("未找到 Node.js，无法启动企微智能机器人")
        if not (APP_DIR / "node_modules" / "@wecom" / "aibot-node-sdk").exists():
            raise RuntimeError("企微 SDK 未安装，请先在 websocket-bot 目录执行 npm install")
        self.process = await asyncio.create_subprocess_exec(
            node,
            str(BRIDGE_SCRIPT),
            cwd=str(APP_DIR),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        await self._write({"type": "start", "botId": self.bot_id, "secret": self.secret})

    async def send_markdown(self, chat_id: str, content: str) -> None:
        await self._write({"type": "reply", "chatId": chat_id, "content": content})

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if not process:
            return
        if process.returncode is None:
            try:
                await self._write_to_process(process, {"type": "stop"})
                await asyncio.wait_for(process.wait(), timeout=3)
            except (BrokenPipeError, asyncio.TimeoutError):
                process.terminate()
                await process.wait()
        for task in (self._stdout_task, self._stderr_task):
            if task and not task.done():
                task.cancel()

    async def _write(self, payload: dict) -> None:
        process = self.process
        if not process or process.returncode is not None:
            raise RuntimeError("企微智能机器人连接进程未运行")
        async with self._write_lock:
            await self._write_to_process(process, payload)

    @staticmethod
    async def _write_to_process(process: asyncio.subprocess.Process, payload: dict) -> None:
        if not process.stdin:
            raise RuntimeError("企微智能机器人连接进程不可写")
        process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def _read_stdout(self) -> None:
        process = self.process
        assert process and process.stdout
        while line := await process.stdout.readline():
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.log("企微桥返回了无法解析的数据")
                continue
            event_type = event.get("type")
            if event_type == "message":
                asyncio.create_task(self.on_message(event))
            elif event_type == "status":
                self.log(f"企微智能机器人：{event.get('message', '')}")
            elif event_type == "error":
                self.log(f"企微智能机器人错误：{event.get('message', '未知错误')}")
            elif event_type == "reply_sent":
                self.log("企微回复已发送")

    async def _read_stderr(self) -> None:
        process = self.process
        assert process and process.stderr
        while line := await process.stderr.readline():
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                self.log(f"企微 SDK：{message}")
