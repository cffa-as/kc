#!/usr/bin/env python3
"""Capture browser WebSocket frames through Chrome DevTools Protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests
import websockets


DEFAULT_URL = "https://www.ss911.cn/"
DEFAULT_PORT = 9222
SYNC_SETTLE_SECONDS = 3.0
DEFAULT_PROFILE_DIR = Path.home() / "Library/Application Support/KC WebSocket Bot/chrome-profile"
REDACT_KEYS = {
    "i", "p", "password", "token", "login_token", "api_key",
    "authorization", "cookie", "set-cookie", "userpwd",
    "u",
}

def login_settings(payload: str) -> dict[str, Any] | None:
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("i") or not data.get("device"):
        return None
    try:
        login_z = int(data.get("Z", 1))
    except (TypeError, ValueError):
        login_z = 1
    return {
        "login_token": str(data["i"]),
        "login_device": str(data["device"]),
        "login_p": str(data.get("p", "")),
        "login_z": login_z,
    }


def sync_login_config(config_path: Path, payload: str) -> bool:
    login = login_settings(payload)
    if not login:
        return False
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法更新机器人配置 {config_path}: {exc}") from exc
    if all(config.get(key) == value for key, value in login.items()):
        return False
    config.update(login)
    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.chmod(0o600)
    temp_path.replace(config_path)
    config_path.chmod(0o600)
    return True


def u_settings(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    if not (parts.hostname or "").lower().endswith("ss911.cn"):
        return {}
    values = dict(parse_qsl(parts.query, keep_blank_values=True))
    value = values.get("u", "").strip()
    return {"u": quote(value, safe="")} if value else {}


def sync_u_config(config_path: Path, url: str) -> bool:
    updates = u_settings(url)
    if not updates:
        return False
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法更新机器人 u 配置 {config_path}: {exc}") from exc
    if config.get("u") == updates["u"]:
        return False
    config["u"] = updates["u"]
    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.chmod(0o600)
    temp_path.replace(config_path)
    config_path.chmod(0o600)
    return True


def redact_value(value: Any, key: str = "") -> Any:
    if key.lower() in REDACT_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_payload(payload: str) -> str:
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        for key in REDACT_KEYS:
            payload = re.sub(
                rf'("{re.escape(key)}"\s*:\s*)"[^"]*"',
                r'\1"<redacted>"',
                payload,
                flags=re.IGNORECASE,
            )
        return payload
    return json.dumps(redact_value(parsed), ensure_ascii=False, separators=(",", ":"))


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, "<redacted>" if key.lower() in REDACT_KEYS else value) for key, value in parse_qsl(parts.query)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def chrome_path() -> str:
    candidates = [
        os.environ.get("CHROME_BIN", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("找不到 Google Chrome，请设置 CHROME_BIN")


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_target(port: int, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    endpoint = f"http://127.0.0.1:{port}/json/list"
    while time.monotonic() < deadline:
        try:
            targets = get_json(endpoint)
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target
        except Exception:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"Chrome CDP {port} 启动超时")


async def cdp_command(ws, sequence: int, method: str, params: dict[str, Any] | None = None) -> int:
    await ws.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
    return sequence + 1


def event_record(
    direction: str,
    url: str,
    request_id: str,
    target_id: str,
    payload: str = "",
    opcode: int | None = None,
) -> dict[str, Any]:
    return {
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "direction": direction,
        "url": redact_url(url),
        "request_id": request_id,
        "target_id": target_id,
        "opcode": opcode,
        "payload": redact_payload(payload),
    }


async def capture_target(
    target: dict[str, Any],
    output,
    port: int,
    lock: asyncio.Lock,
    config_path: Path,
    login_captured: asyncio.Event,
) -> None:
    urls: dict[str, str] = {}
    sequence = 1
    async with websockets.connect(
        target["webSocketDebuggerUrl"],
        origin=f"http://127.0.0.1:{port}",
        ping_interval=None,
    ) as ws:
        sequence = await cdp_command(ws, sequence, "Network.enable")
        sequence = await cdp_command(ws, sequence, "Page.enable")
        await ws.send(json.dumps({"id": sequence, "method": "Runtime.enable", "params": {}}))
        while True:
            message = json.loads(await ws.recv())
            method = message.get("method", "")
            params = message.get("params") or {}
            request_id = str(params.get("requestId", ""))
            target_id = str(target.get("id", ""))
            if method == "Network.requestWillBeSent":
                request_url = str((params.get("request") or {}).get("url", ""))
                async with lock:
                    updated = sync_u_config(config_path, request_url)
                if updated:
                    print(f"u 参数已自动更新：{config_path}")
                continue
            if method == "Network.webSocketCreated":
                url = str(params.get("url", ""))
                urls[request_id] = url
                record = event_record("created", url, request_id, target_id)
            elif method == "Network.webSocketFrameSent":
                frame = params.get("response") or {}
                payload = str(frame.get("payloadData", ""))
                async with lock:
                    if login_settings(payload):
                        if sync_login_config(config_path, payload):
                            print(f"登录参数已自动更新：{config_path}")
                        else:
                            print("已确认浏览器登录参数仍然有效。")
                        login_captured.set()
                record = event_record(
                    "sent", urls.get(request_id, ""), request_id, target_id,
                    payload, frame.get("opcode"),
                )
            elif method == "Network.webSocketFrameReceived":
                frame = params.get("response") or {}
                record = event_record(
                    "received", urls.get(request_id, ""), request_id, target_id,
                    str(frame.get("payloadData", "")), frame.get("opcode"),
                )
            elif method == "Network.webSocketClosed":
                record = event_record("closed", urls.get(request_id, ""), request_id, target_id)
                urls.pop(request_id, None)
            else:
                continue
            async with lock:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
            if record["direction"] in {"sent", "received"}:
                print(f"{record['direction']:>8} {record['url']} {record['payload'][:180]}")


async def capture(
    output: Path, port: int, config_path: Path,
    stop_after_login: bool = False, timeout: float = 120.0,
) -> None:
    print("已开始抓包。首次使用请登录；以后会复用登录状态并自动更新机器人参数。完成后按 Ctrl-C。")
    lock = asyncio.Lock()
    login_captured = asyncio.Event()
    deadline = time.monotonic() + timeout
    tasks: dict[str, asyncio.Task] = {}
    with output.open("w", encoding="utf-8") as handle:
        while True:
            try:
                targets = await asyncio.to_thread(get_json, f"http://127.0.0.1:{port}/json/list")
            except Exception:
                targets = []
            for target in targets:
                target_id = str(target.get("id", ""))
                if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
                    continue
                task = tasks.get(target_id)
                if task is None or task.done():
                    print(f"已监听页面：{target.get('url', '')}")
                    tasks[target_id] = asyncio.create_task(
                        capture_target(target, handle, port, lock, config_path, login_captured)
                    )
            if stop_after_login and login_captured.is_set():
                await asyncio.sleep(SYNC_SETTLE_SECONDS)
                for task in tasks.values():
                    task.cancel()
                await asyncio.gather(*tasks.values(), return_exceptions=True)
                return
            if stop_after_login and time.monotonic() >= deadline:
                raise TimeoutError(f"{timeout:.0f} 秒内未捕获到登录包")
            await asyncio.sleep(0.5)


def load_frames(path: Path) -> list[dict[str, Any]]:
    frames = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if value.get("direction") in {"sent", "received"}:
            frames.append(value)
    return frames


def ai_report(config_path: Path, frames: list[dict[str, Any]], report_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    api_key = str(config.get("ai_api_key", "")).strip()
    base_url = str(config.get("ai_base_url", "https://api.deepseek.com")).rstrip("/")
    model = str(config.get("ai_model", "deepseek-v4-flash"))
    if not api_key:
        report_path.write_text("未配置 ai_api_key，跳过 AI 分析。\n", encoding="utf-8")
        print(f"未配置 AI key，抓包已保存：{report_path}")
        return

    transcript = "\n".join(
        f"{item['time']} {item['direction']} {item['url']} {item['payload']}"
        for item in frames
    )
    transcript = transcript[-120000:]
    prompt = (
        "分析下面脱敏后的推理学院 WebSocket 帧。请只依据帧中证据回答，不要猜测线路号映射。\n"
        "输出：1. 登录、JoinRoom、jump、成功入房、心跳的时序；"
        "2. jump 的 r/l 与当前连接的关系；3. 机器人应采用的重试、超时和重连策略；"
        "4. 可直接修改 bot/core.py 的具体建议。不要复述任何 redacted 值。\n\n"
        + transcript
    )
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": "你是 WebSocket 协议分析工程师。"},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=90,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        content = f"AI 分析失败，原始帧仍已保存。\n\n{type(exc).__name__}: {exc}"
        print(f"AI 分析失败，帧记录仍已保存：{report_path}")
    else:
        print(f"AI 分析已保存：{report_path}")
    report_path.write_text(str(content).strip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture WSS frames from a dedicated Chrome via CDP")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--fresh-profile", action="store_true")
    parser.add_argument("--sync-login", action="store_true", help="捕获并保存登录参数后自动退出")
    parser.add_argument("--sync-timeout", type=float, default=120.0)
    parser.add_argument("--no-ai", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or Path("captures") / f"ws-{stamp}.jsonl"
    report = args.report or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    report = report.resolve()
    config_path = args.config.expanduser().resolve()
    temporary_profile = args.fresh_profile
    profile_dir = (
        Path(tempfile.mkdtemp(prefix="kc-cdp-chrome-"))
        if temporary_profile else args.profile_dir.expanduser().resolve()
    )
    profile_dir.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        process = subprocess.Popen([
            chrome_path(),
            f"--remote-debugging-port={args.port}",
            f"--remote-allow-origins=http://127.0.0.1:{args.port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            args.url,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for_target(args.port)
        try:
            asyncio.run(capture(
                output, args.port, config_path,
                stop_after_login=args.sync_login, timeout=args.sync_timeout,
            ))
        except TimeoutError as exc:
            print(f"登录参数同步失败：{exc}")
            return 1
        except (KeyboardInterrupt, websockets.exceptions.ConnectionClosed):
            print("已停止抓包。")
        frames = load_frames(output)
        if not args.no_ai and frames:
            ai_report(Path(__file__).resolve().parents[1] / "config.json", frames, report)
        print(f"帧记录已保存：{output}")
        return 0
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if temporary_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
