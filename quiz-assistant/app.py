#!/usr/bin/env python3
"""Small macOS helper for answering a browser quiz with a vision model."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote_plus, urlencode

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageChops, ImageGrab, ImageStat
import requests
import websockets

from local_knowledge import LocalKnowledge, SearchResult, answer_is_grounded

try:
    import pyautogui
except Exception:  # pragma: no cover - allows config/self-test without GUI automation
    pyautogui = None

try:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        CGWindowListCreateImage,
        CGImageGetBytesPerRow,
        CGImageGetDataProvider,
        CGImageGetHeight,
        CGImageGetWidth,
        CGDataProviderCopyData,
        CGRectMake,
        kCGNullWindowID,
        kCGWindowBounds,
        kCGWindowLayer,
        kCGWindowListExcludeDesktopElements,
        kCGWindowListOptionOnScreenOnly,
        kCGWindowImageDefault,
        kCGWindowOwnerName,
        kCGWindowName,
    )
except Exception:  # pragma: no cover - non-macOS fallback
    CGWindowListCopyWindowInfo = None
    CGWindowListCreateImage = None


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "question_agent_config.json"
LOG_PATH = APP_DIR / "question_agent.log"
LOCAL_KNOWLEDGE = LocalKnowledge(APP_DIR)
HTTP_SESSIONS = threading.local()
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
ROOM_SERVERS = [
    ("wss://kg3.ss911.cn:6103/", "https://t1.ss911.cn"),
    ("wss://kg2.ss911.cn:6102/", "https://t1.ss911.cn"),
    ("wss://kg4.ss911.cn:6104/", "https://t1.ss911.cn"),
    ("wss://kg1.ss911.cn:6101/", "https://t1.ss911.cn"),
]
ROOM_JOIN_TIMEOUT = 4.0
ROOM_JOIN_RETRY_INTERVAL = 0.5
ROOM_QWEN_MIN_LENGTH = 5

DEFAULTS = {
    "model": "qwen3.5-flash",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "",
    "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta",
    "gemini_model": "gemini-3.7-flash",
    "gemini_api_key": "",
    "knowledge_enabled": False,
    "knowledge_base_id": "",
    "web_search_enabled": False,
    "google_search_enabled": True,
    "dry_run_enabled": False,
    "answer_mode": "screen",
    "bot_config_path": str(APP_DIR.parent / "websocket-bot" / "config.json"),
    "room": {"id": "", "password": "", "player": ""},
    "question": {"x": 10, "y": 390, "w": 412, "h": 188},
    "input": {"x_percent": 50.0, "y_percent": 94.0},
    "send": {"x_percent": 94.0, "y_percent": 94.0},
    "threshold": 7.0,
    "poll_seconds": 0.03,
    "lock_enabled": False,
    "window": None,
}


@dataclass
class BrowserWindow:
    owner: str
    title: str
    x: int
    y: int
    w: int
    h: int
    index: int

    @property
    def label(self) -> str:
        title = self.title or "(untitled)"
        return f"{self.owner}: {title}  [{self.x},{self.y} {self.w}x{self.h}]"


def load_config() -> dict:
    data = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for key in (
                "model", "base_url", "api_key", "knowledge_enabled", "knowledge_base_id",
                "gemini_base_url", "gemini_model", "gemini_api_key",
                "web_search_enabled", "google_search_enabled", "dry_run_enabled", "answer_mode", "bot_config_path",
                "threshold", "poll_seconds", "lock_enabled", "window",
            ):
                if key in saved:
                    data[key] = saved[key]
            for key in ("room", "question", "input", "send"):
                if isinstance(saved.get(key), dict):
                    data[key].update(saved[key])
        except (OSError, ValueError):
            pass
    return data


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


def chrome_windows() -> list[BrowserWindow]:
    if CGWindowListCopyWindowInfo is None:
        return []
    try:
        flags = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
        raw = CGWindowListCopyWindowInfo(flags, kCGNullWindowID) or []
    except Exception:
        return []
    out: list[BrowserWindow] = []
    for item in raw:
        owner = str(item.get(kCGWindowOwnerName, ""))
        if owner not in {"Google Chrome", "Chromium", "Microsoft Edge"}:
            continue
        if int(item.get(kCGWindowLayer, 0)) != 0:
            continue
        bounds = item.get(kCGWindowBounds) or {}
        try:
            x, y = int(bounds.get("X", 0)), int(bounds.get("Y", 0))
            w, h = int(bounds.get("Width", 0)), int(bounds.get("Height", 0))
        except (TypeError, ValueError):
            continue
        if w < 240 or h < 180:
            continue
        out.append(BrowserWindow(owner, str(item.get(kCGWindowName, "") or ""), x, y, w, h, len(out)))
    return out


def saved_window(data: dict) -> Optional[BrowserWindow]:
    value = data.get("window")
    if not isinstance(value, dict):
        return None
    try:
        return BrowserWindow(
            str(value["owner"]), str(value["title"]), int(value["x"]), int(value["y"]),
            int(value["w"]), int(value["h"]), int(value.get("index", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def window_as_dict(window: BrowserWindow) -> dict:
    return {"owner": window.owner, "title": window.title, "x": window.x, "y": window.y, "w": window.w, "h": window.h, "index": window.index}


def cg_image_to_pil(cg_image) -> Image.Image:
    width, height = CGImageGetWidth(cg_image), CGImageGetHeight(cg_image)
    stride = CGImageGetBytesPerRow(cg_image)
    data = CGDataProviderCopyData(CGImageGetDataProvider(cg_image))
    return Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", stride, 1).convert("RGB")


def image_grab(x: int, y: int, w: int, h: int) -> Image.Image:
    """Capture the visible screen inside the configured red box."""
    if CGWindowListCreateImage is not None:
        try:
            cg_image = CGWindowListCreateImage(
                CGRectMake(x, y, w, h), kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID, kCGWindowImageDefault,
            )
            image = cg_image_to_pil(cg_image)
            if image.size != (w, h):
                image = image.resize((w, h), Image.Resampling.LANCZOS)
            return image
        except Exception:
            pass
    try:
        return ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("RGB")
    except TypeError:  # older Pillow
        return ImageGrab.grab(bbox=(x, y, x + w, y + h)).convert("RGB")
    except Exception:
        if pyautogui is None:
            raise
        return pyautogui.screenshot(region=(x, y, w, h)).convert("RGB")


def frame_signature(image: Image.Image) -> Image.Image:
    return image.convert("L").resize((64, 32))


def image_delta(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        b = b.resize(a.size)
    return float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0])


def question_edge_score(frame: Image.Image) -> float:
    """Fresh question cards are visually quiet below the centered question text."""
    gray = frame.convert("L").resize((64, 32)).crop((0, 16, 64, 32))
    upper = gray.crop((0, 0, 64, 15))
    lower = gray.crop((0, 1, 64, 16))
    return float(ImageStat.Stat(ImageChops.difference(upper, lower)).mean[0])


def looks_like_question(frame: Image.Image) -> bool:
    # The result card adds red answer text near the top; a fresh question does not.
    rgb = frame.convert("RGB").resize((64, 32))
    pixels = list(rgb.getdata())
    blue_pixels = sum(1 for r, g, b in pixels if b - r > 12 and b - g > 5 and b < 210)
    blue_ratio = blue_pixels / len(pixels)
    upper_pixels = list(rgb.crop((0, 0, 64, 18)).getdata())
    red_pixels = sum(1 for r, g, b in upper_pixels if r - g > 18 and r - b > 15 and r > 120)
    red_ratio = red_pixels / len(upper_pixels)
    return question_edge_score(frame) < 7.2 and blue_ratio > 0.015 and red_ratio < 0.006


def apple_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def normalized_window_title(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def same_browser_window(saved: BrowserWindow, current: BrowserWindow) -> bool:
    if saved.owner != current.owner:
        return False
    saved_title = normalized_window_title(saved.title)
    current_title = normalized_window_title(current.title)
    return bool(
        saved.title == current.title
        or saved_title and current_title
        and (saved_title in current_title or current_title in saved_title)
    )


def resolve_browser_window(window: BrowserWindow) -> Optional[BrowserWindow]:
    candidates = [current for current in chrome_windows() if current.owner == window.owner]
    matches = [current for current in candidates if same_browser_window(window, current)]
    if matches:
        return min(matches, key=lambda current: abs(current.x - window.x) + abs(current.y - window.y))
    if len(candidates) == 1:
        return candidates[0]
    return None


def set_window_bounds(window: BrowserWindow) -> tuple[bool, str]:
    """Use the macOS accessibility bridge exposed by AppleScript."""
    if window.owner not in {"Google Chrome", "Chromium", "Microsoft Edge"}:
        return False, "该窗口不是受支持的 Chromium 浏览器"
    current = resolve_browser_window(window)
    if not current:
        return False, f"没有找到目标窗口：{window.owner}: {window.title}"
    app_name = current.owner
    title = apple_quote(current.title)
    bounds = f"{{{window.x}, {window.y}, {window.x + window.w}, {window.y + window.h}}}"
    observed_bounds = f"{{{current.x}, {current.y}, {current.x + current.w}, {current.y + current.h}}}"
    script = f'''tell application {apple_quote(app_name)}
set targetBounds to {bounds}
set observedBounds to {observed_bounds}
try
    set bounds of (first window whose title is {title}) to targetBounds
on error
    repeat with candidateWindow in windows
        if (get bounds of candidateWindow) is observedBounds then
            set bounds of candidateWindow to targetBounds
            return
        end if
    end repeat
    error "目标窗口在锁定过程中发生变化"
end try
end tell'''
    try:
        result = subprocess.run(["osascript", "-e", script], text=True, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode:
        return False, (result.stderr or "osascript failed").strip()
    return True, ""


def screen_point(window: BrowserWindow, x_percent: float, y_percent: float) -> tuple[int, int]:
    return (
        window.x + round(window.w * x_percent / 100.0),
        window.y + round(window.h * y_percent / 100.0),
    )


def http_session() -> requests.Session:
    session = getattr(HTTP_SESSIONS, "session", None)
    if session is None:
        session = requests.Session()
        HTTP_SESSIONS.session = session
    return session


CLIPBOARD_LOCK = threading.Lock()


def copy_answer(answer: str) -> None:
    with CLIPBOARD_LOCK:
        subprocess.run(["pbcopy"], input=answer.encode("utf-8"), check=True)


def google_search_url(question: str) -> str:
    query = (
        "推理学院 " + question.strip()
        + "。只输出一个最适合填入的最短答案；不要解释、斜杠备选、标点前缀、Markdown 或其他文字。"
    )
    return "https://www.google.com/search?" + urlencode({"q": query})


def google_search_bounds(screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    window_width = min(600, max(420, screen_width // 3))
    left = max(0, screen_width - window_width)
    top = 27
    bottom = max(top + 400, screen_height - 27)
    return left, top, screen_width, bottom


def open_google_search(question: str, screen_size: Optional[tuple[int, int]] = None) -> str:
    url = google_search_url(question)
    screen_width, screen_height = screen_size or (1440, 900)
    left, top, right, bottom = google_search_bounds(screen_width, screen_height)
    script = f'''tell application "Google Chrome"
set newWindow to make new window
set URL of active tab of newWindow to {apple_quote(url)}
set bounds of newWindow to {{{left}, {top}, {right}, {bottom}}}
activate
end tell'''
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        subprocess.Popen(
            ["open", "-na", "Google Chrome", "--args", "--new-window", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return url


def load_bot_login(config_path: str) -> tuple[str, str, str, int]:
    path = Path(config_path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法读取机器人配置 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("机器人配置的 JSON 顶层必须是对象")
    token = str(data.get("login_token", "")).strip()
    device = str(data.get("login_device", "")).strip()
    login_p = str(data.get("login_p", "")).strip()
    try:
        login_z = int(data.get("login_z", 1))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("机器人配置中的 login_z 必须是整数") from exc
    if not token or not device:
        raise RuntimeError("机器人配置缺少 login_token 或 login_device")
    return token, device, login_p, login_z


def room_server_index_for_line(line_id: int) -> Optional[int]:
    host = f"kg{line_id}"
    return next(
        (index for index, (url, _origin) in enumerate(ROOM_SERVERS) if f"//{host}." in url),
        None,
    )


def next_room_server_index(current_index: int, pinned_index: Optional[int] = None) -> int:
    return pinned_index if pinned_index is not None else (current_index + 1) % len(ROOM_SERVERS)


def parse_room_say(message: str) -> Optional[tuple[str, str, str]]:
    if not message.startswith("RoomSay{"):
        return None
    try:
        data = json.loads(message[len("RoomSay"):])
        user = data.get("u")
        if not isinstance(user, list) or len(user) < 3:
            return None
        content = str(data.get("m", "")).strip()
        if not content:
            return None
        return str(user[1]), str(user[2]), content
    except (TypeError, ValueError):
        return None


def paste_and_send(answer: str, window: BrowserWindow, input_x: float, input_y: float, send_x: float, send_y: float) -> None:
    if pyautogui is None:
        raise RuntimeError("pyautogui 不可用")
    input_point = screen_point(window, input_x, input_y)
    send_point = screen_point(window, send_x, send_y)
    pyautogui.doubleClick(*input_point, interval=0.08)
    pyautogui.hotkey("command", "a")
    copy_answer(answer)
    pyautogui.hotkey("command", "v")
    time.sleep(0.08)
    pyautogui.click(*send_point)


def model_tools(settings: dict) -> list[dict]:
    tools = []
    if settings.get("knowledge_enabled"):
        tools.append({"type": "file_search", "vector_store_ids": [settings["knowledge_base_id"]]})
    if settings.get("web_search_enabled"):
        tools.append({"type": "web_search"})
    return tools


def knowledge_prompt(settings: dict) -> str:
    if not settings.get("knowledge_enabled"):
        return ""
    if settings.get("web_search_enabled"):
        return (
            "必须先检索已配置的知识库，并优先采用知识库资料。"
            "如果知识库没有相关内容，必须改用联网搜索；不得凭空猜测。\n\n"
        )
    return (
        "必须先检索已配置的知识库，并以检索到的资料为唯一事实依据。"
        "即使你知道或猜测答案，也不得用知识库以外的信息补全；知识库无结果时不要猜。\n\n"
    )


def tool_choice(settings: dict):
    if settings.get("knowledge_enabled"):
        return {"type": "file_search"}
    return "auto"


def build_model_request(encoded: str, settings: dict) -> tuple[str, dict, bool]:
    prompt = knowledge_prompt(settings) + "推理学院问题：请读取图片中的题目并给出最终答案。只输出一个最适合填入的最短答案；不要解释、斜杠备选、标点前缀、Markdown 或其他文字。"
    tools = model_tools(settings)
    if tools:
        return settings["base_url"].rstrip("/") + "/responses", {
            "model": settings["model"].strip(),
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}"},
                ],
            }],
            "tools": tools,
            "tool_choice": tool_choice(settings),
            **({"include": ["file_search_call.results"]} if settings.get("knowledge_enabled") else {}),
            "temperature": 0,
            "max_output_tokens": 32,
            "enable_thinking": False,
            "store": False,
        }, True
    return settings["base_url"].rstrip("/") + "/chat/completions", {
        "model": settings["model"].strip(),
        "temperature": 0,
        "max_tokens": 32,
        "enable_thinking": False,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }],
    }, False


def build_text_model_request(question: str, settings: dict) -> tuple[str, dict, bool]:
    prompt = knowledge_prompt(settings) + "推理学院问题：" + question.strip() + "\n\n只输出一个最适合填写的最短答案；不要解释、斜杠备选、标点前缀、Markdown 或其他文字。"
    tools = model_tools(settings)
    if tools:
        return settings["base_url"].rstrip("/") + "/responses", {
            "model": settings["model"].strip(),
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }],
            "tools": tools,
            "tool_choice": tool_choice(settings),
            **({"include": ["file_search_call.results"]} if settings.get("knowledge_enabled") else {}),
            "temperature": 0,
            "max_output_tokens": 64,
            "enable_thinking": False,
            "store": False,
        }, True
    return settings["base_url"].rstrip("/") + "/chat/completions", {
        "model": settings["model"].strip(),
        "temperature": 0,
        "max_tokens": 64,
        "enable_thinking": False,
        "messages": [{"role": "user", "content": prompt}],
    }, False


def build_local_text_model_request(question: str, result: SearchResult, settings: dict) -> tuple[str, dict, bool]:
    context = "\n\n".join(
        f"[资料 {index}：{Path(hit.source).name} {hit.locator}]\n{hit.snippet}"
        for index, hit in enumerate(result.hits, 1)
    )
    prompt = (
        "请只根据下面的推理学院资料回答问题。只输出一个最适合填写的最短答案；"
        "不要解释、斜杠备选、标点前缀、Markdown 或其他文字。\n\n"
        f"问题：{question.strip()}\n\n资料：\n{context}"
    )
    return settings["base_url"].rstrip("/") + "/chat/completions", {
        "model": settings["model"].strip(),
        "temperature": 0,
        "max_tokens": 32,
        "enable_thinking": False,
        "messages": [{"role": "user", "content": prompt}],
    }, False


def local_search_details(result: SearchResult, direct: bool = False) -> list[str]:
    status = "包含明确答案" if direct else ("可生成回答" if result.confident else "置信度不足")
    details = [
        f"本地知识库检索：{result.elapsed_ms:.1f}ms；覆盖率 {result.coverage:.0%}；{status}"
    ]
    for index, hit in enumerate(result.hits[:3], 1):
        details.append(
            f"本地命中 {index}：{Path(hit.source).name} {hit.locator}；得分 {hit.score:.1f}"
        )
    return details


def validate_knowledge_search(body: dict) -> None:
    calls = [item for item in body.get("output", []) if item.get("type") == "file_search_call"]
    if not calls:
        raise RuntimeError(
            "知识库未被调用。请检查知识库 ID，并将 Base URL 改为知识库详情页所属工作空间的专属地址。"
        )
    if not any(item.get("results") for item in calls):
        raise RuntimeError(
            "知识库检索到 0 条资料。请确认 PDF 已上传且解析完成、知识库 ID 正确，"
            "并使用知识库所属工作空间的专属 Base URL。"
        )


def knowledge_search_details(body: dict) -> list[str]:
    calls = [item for item in body.get("output", []) if item.get("type") == "file_search_call"]
    queries = [str(query) for item in calls for query in item.get("queries", [])]
    results = [result for item in calls for result in (item.get("results") or [])]
    details = [f"知识库检索：查询 {' / '.join(queries) or '(未返回)'}；命中 {len(results)} 条"]
    for index, result in enumerate(results[:3], 1):
        filename = result.get("filename") or result.get("file_id") or "未知文件"
        score = result.get("score")
        score_text = f"；相似度 {score:.3f}" if isinstance(score, (int, float)) else ""
        text = " ".join(str(result.get("text", "")).split())
        terms = [term for term in (queries[0].split() if queries else []) if len(term) > 1]
        position = 0
        for term in terms:
            found = text.find(term, position)
            if found >= 0:
                position = found
        start = max(0, position - 50)
        snippet = ("..." if start else "") + text[start:start + 180]
        details.append(f"知识库命中 {index}：{filename}{score_text}；{snippet}")
    return details


def extract_answer(body: dict, responses_api: bool, knowledge_enabled: bool = False) -> str:
    try:
        if responses_api:
            if knowledge_enabled:
                validate_knowledge_search(body)
            answer = "".join(
                str(part.get("text", ""))
                for item in body.get("output", [])
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
        else:
            answer = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"API 返回格式异常: {body}") from exc
    if isinstance(answer, list):
        answer = "".join(str(part.get("text", "")) for part in answer if isinstance(part, dict))
    answer = " ".join(str(answer).split()).strip()
    if not answer:
        raise RuntimeError(f"API 返回空答案: {body}")
    return answer


def request_answer(
    url: str, payload: dict, responses_api: bool, api_key: str,
    knowledge_enabled: bool = False, web_search_enabled: bool = False,
) -> tuple[str, list[str]]:
    def post(current_payload: dict) -> dict:
        response = http_session().post(
            url,
            json=current_payload,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=(3, 20),
        )
        if not response.ok:
            raise RuntimeError(f"API {response.status_code}: {response.text[:500]}")
        return response.json()

    try:
        body = post(payload)
        details = knowledge_search_details(body) if knowledge_enabled else []
        if knowledge_enabled and web_search_enabled and not any(
            item.get("results") for item in body.get("output", []) if item.get("type") == "file_search_call"
        ):
            fallback = {**payload, "tools": [{"type": "web_search"}], "tool_choice": "auto"}
            fallback.pop("include", None)
            body = post(fallback)
            details.append("知识库未命中，已改用联网搜索。")
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"API 请求失败: {exc}") from exc
    answer = extract_answer(body, responses_api, knowledge_enabled and not web_search_enabled)
    return answer, details


def call_model(image: Image.Image, settings: dict) -> tuple[str, list[str]]:
    api_key = settings["api_key"]
    if not api_key.strip():
        raise RuntimeError("请先填写 API key 并保存配置")
    from io import BytesIO

    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    url, payload, responses_api = build_model_request(encoded, settings)
    return request_answer(
        url, payload, responses_api, api_key,
        bool(settings.get("knowledge_enabled")), bool(settings.get("web_search_enabled")),
    )


def call_text_model(question: str, settings: dict) -> tuple[str, list[str]]:
    api_key = settings["api_key"]
    local_details: list[str] = []
    if settings.get("knowledge_enabled"):
        try:
            result = LOCAL_KNOWLEDGE.search(question)
            direct_answer = LOCAL_KNOWLEDGE.direct_answer(question, result.hits)
            local_details.extend(local_search_details(result, bool(direct_answer)))
            if direct_answer:
                local_details.append("本地资料包含明确字段，已直接提取答案。")
                return direct_answer, local_details
            if result.confident:
                if not api_key.strip():
                    raise RuntimeError("请先填写 API key 并保存配置")
                local_url, local_payload, local_responses_api = build_local_text_model_request(
                    question, result, settings,
                )
                answer, _details = request_answer(
                    local_url, local_payload, local_responses_api, api_key,
                )
                if answer_is_grounded(answer, result.hits):
                    local_details.append("答案已由本地资料生成并校验。")
                    return answer, local_details
                local_details.append("本地生成答案未在资料中找到，已改用远端知识库。")
        except Exception as exc:
            local_details.append(f"本地知识库不可用，已改用远端知识库：{exc}")
    if not api_key.strip():
        raise RuntimeError("请先填写 API key 并保存配置")
    url, payload, responses_api = build_text_model_request(question, settings)
    answer, details = request_answer(
        url, payload, responses_api, api_key,
        bool(settings.get("knowledge_enabled")), bool(settings.get("web_search_enabled")),
    )
    return answer, local_details + details


def extract_gemini_interaction_answer(body: dict) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    texts = [
        str(content.get("text", "")).strip()
        for step in body.get("steps", [])
        if step.get("type") == "model_output"
        for content in step.get("content", [])
        if content.get("type") == "text" and content.get("text")
    ]
    if texts:
        return texts[-1]
    raise RuntimeError(f"Gemini 返回中没有文本答案: {body}")


def call_gemini_google_search(question: str, settings: dict) -> tuple[str, list[str]]:
    api_key = str(settings.get("gemini_api_key", "")).strip() or str(settings.get("api_key", "")).strip()
    if not api_key:
        raise RuntimeError("请先填写 Gemini API Key")
    model = str(settings.get("gemini_model", "")).strip() or DEFAULTS["gemini_model"]
    base_url = str(settings.get("gemini_base_url", "")).strip() or DEFAULTS["gemini_base_url"]
    prompt = (
        f"推理学院问题：{question.strip()}\n\n"
        "请使用 Google Search 查证答案。只输出一个最适合填写的最短答案；"
        "不要解释、斜杠备选、标点前缀、Markdown、搜索过程或引用。"
    )
    try:
        is_google_native = "generativelanguage.googleapis.com" in base_url and not base_url.rstrip("/").endswith("/openai")
        if is_google_native:
            url = base_url.rstrip("/") + "/interactions"
            payload = {"model": model, "input": prompt, "tools": [{"type": "google_search"}]}
            headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        else:
            url = base_url.rstrip("/") + "/chat/completions"
            payload = {
                "model": model,
                "temperature": 0,
                "max_tokens": 128 if "flash-lite" in model else 512,
                "enable_thinking": False,
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        response = http_session().post(url, json=payload, headers=headers, timeout=(5, 60))
        if not response.ok:
            raise RuntimeError(f"Gemini API {response.status_code}: {response.text[:500]}")
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"Gemini API 请求失败: {exc}") from exc
    answer = extract_gemini_interaction_answer(body) if is_google_native else extract_answer(body, False)
    provider = "Google 原生" if is_google_native else base_url.rstrip("/")
    return answer, [f"Gemini Google Search 已调用：{model}（{provider}）"]


def call_room_answers(question: str, settings: dict, on_answer=None) -> tuple[list[tuple[str, str, list[str]]], list[tuple[str, Exception]]]:
    jobs = [("主模型", call_text_model)]
    if settings.get("google_search_enabled", False):
        jobs.append(("Gemini Google Search", call_gemini_google_search))
    answers: list[tuple[str, str, list[str]]] = []
    errors: list[tuple[str, Exception]] = []
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="answer") as executor:
        pending = [(label, executor.submit(func, question, settings)) for label, func in jobs]
        for label, future in pending:
            try:
                answer, details = future.result()
                answers.append((label, answer, details))
                if on_answer is not None:
                    on_answer(label, answer, details)
            except Exception as exc:
                errors.append((label, exc))
    return answers, errors


class RoomClient:
    def __init__(self, events: queue.Queue):
        self.events = events
        self.thread: Optional[threading.Thread] = None
        self.stop_event: Optional[threading.Event] = None
        self.commands: queue.Queue = queue.Queue()
        self.login_signature = ""
        self.logged_in = False
        self.joined_room_id = ""
        self.target_player = ""

    def login_active_for(self, settings: dict) -> bool:
        return bool(
            self.thread and self.thread.is_alive()
            and self.login_signature == settings["bot_config_path"]
        )

    def set_player(self, player: str) -> None:
        self.target_player = player

    def connect(self, settings: dict) -> None:
        load_bot_login(settings["bot_config_path"])
        self.stop()
        if self.thread and self.thread.is_alive():
            self.thread.join(1.5)
        stop_event = threading.Event()
        self.stop_event = stop_event
        self.commands = queue.Queue()
        self.login_signature = settings["bot_config_path"]
        self.logged_in = False
        self.joined_room_id = ""
        self.thread = threading.Thread(
            target=self._thread_main,
            args=(settings["bot_config_path"], stop_event, self.commands),
            daemon=True,
        )
        self.thread.start()

    def join(self, settings: dict) -> None:
        if not self.login_active_for(settings) or not self.logged_in:
            raise RuntimeError("请先点击“连接/登录”，登录成功后再加入房间")
        room = settings["room"].copy()
        self.set_player(room["player"])
        self.joined_room_id = ""
        self.commands.put(room)

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        self.logged_in = False
        self.joined_room_id = ""

    def _thread_main(
        self, config_path: str,
        stop_event: threading.Event, commands: queue.Queue,
    ) -> None:
        try:
            asyncio.run(self._listen(config_path, stop_event, commands))
        except Exception as exc:
            if not stop_event.is_set():
                self.events.put(("room_error", str(exc)))
        finally:
            if self.stop_event is stop_event:
                self.logged_in = False
                self.joined_room_id = ""

    async def _listen(
        self, config_path: str,
        stop_event: threading.Event, commands: queue.Queue,
    ) -> None:
        server_index = 0
        pinned_server_index = None
        current_room = None
        redirect_room_id = ""
        join_started = 0.0
        join_sent_at = 0.0
        join_attempt = 0
        while not stop_event.is_set():
            token, device, login_p, login_z = load_bot_login(config_path)
            self.logged_in = False
            self.joined_room_id = ""
            ws_url, origin = ROOM_SERVERS[server_index]
            server_name = re.search(r"//([^./:]+)", ws_url)
            server_name = server_name.group(1) if server_name else ws_url
            connection_started = time.monotonic()
            redirected = False
            try:
                self.events.put(("room_diag", f"线路 {server_name} 开始连接。"))
                self.events.put(("room_status", f"正在连接 {ws_url}"))
                async with websockets.connect(
                    ws_url,
                    origin=origin,
                    user_agent_header="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    ping_interval=None,
                    open_timeout=6,
                ) as ws:
                    login_started = time.monotonic()
                    login_payload = {"i": token, "device": device, "Z": login_z, "p": login_p}
                    if redirect_room_id:
                        login_payload["R"] = int(redirect_room_id) if redirect_room_id.isdigit() else redirect_room_id
                        self.events.put(("room_diag", f"线路 {server_name} 登录时请求房间 {redirect_room_id}。"))
                    await ws.send(json.dumps(login_payload))
                    while not stop_event.is_set():
                        try:
                            response = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            self.events.put(("room_diag", f"线路 {server_name} 登录等待超时（5 秒）。"))
                            raise
                        if isinstance(response, str) and response.startswith("Login{"):
                            break
                    else:
                        return
                    self.events.put((
                        "room_diag",
                        f"线路 {server_name} 登录完成，连接耗时 {login_started - connection_started:.2f}s，"
                        f"登录耗时 {time.monotonic() - login_started:.2f}s。",
                    ))
                    redirected_login = bool(redirect_room_id)
                    if not redirected_login:
                        await ws.send(json.dumps({"c": "UserInfo"}))
                        await ws.send(json.dumps({"c": "JoinHall"}))
                    self.logged_in = True
                    self.events.put(("room_connected", ""))
                    if current_room:
                        join_attempt += 1
                        join_sent_at = time.monotonic()
                        self.events.put((
                            "room_diag",
                            f"线路 {server_name} 第 {join_attempt} 次发送 JoinRoom，房间 {current_room['id']}。",
                        ))
                        await ws.send(json.dumps({
                            "RoomId": current_room["id"],
                            "Password": current_room["password"],
                            "c": "JoinRoom",
                        }))
                        join_started = time.monotonic()
                    else:
                        join_started = 0.0
                    last_heartbeat = time.monotonic()
                    while not stop_event.is_set():
                        try:
                            while True:
                                next_room = commands.get_nowait()
                                if not current_room or next_room["id"] != current_room["id"]:
                                    pinned_server_index = None
                                current_room = next_room
                                self.joined_room_id = ""
                                join_started = time.monotonic()
                                join_sent_at = join_started
                                join_attempt += 1
                                self.events.put((
                                    "room_diag",
                                    f"线路 {server_name} 第 {join_attempt} 次发送 JoinRoom，房间 {current_room['id']}。",
                                ))
                                await ws.send(json.dumps({
                                    "RoomId": current_room["id"],
                                    "Password": current_room["password"],
                                    "c": "JoinRoom",
                                }))
                        except queue.Empty:
                            pass
                        if current_room and not self.joined_room_id and join_started:
                            elapsed = time.monotonic() - join_started
                            if pinned_server_index == server_index and elapsed >= ROOM_JOIN_RETRY_INTERVAL:
                                join_attempt += 1
                                join_sent_at = time.monotonic()
                                join_started = join_sent_at
                                self.events.put((
                                    "room_diag",
                                    f"线路 {server_name} 第 {join_attempt} 次重试 JoinRoom，"
                                    f"房间 {current_room['id']}（可能满员）。",
                                ))
                                self.events.put(("room_status", f"房间可能满员，持续在线路 {server_name} 重试。"))
                                await ws.send(json.dumps({
                                    "RoomId": current_room["id"],
                                    "Password": current_room["password"],
                                    "c": "JoinRoom",
                                }))
                                continue
                            if elapsed >= ROOM_JOIN_TIMEOUT:
                                self.events.put((
                                    "room_diag",
                                    f"线路 {server_name} 入房超时：房间 {current_room['id']}，"
                                    f"第 {join_attempt} 次，耗时 {time.monotonic() - join_sent_at:.2f}s。",
                                ))
                                self.events.put(("room_status", "加入房间超时，正在切换服务器。"))
                                redirect_room_id = ""
                                server_index = next_room_server_index(server_index)
                                redirected = True
                                break
                        if time.monotonic() - last_heartbeat >= 25:
                            await ws.send("p")
                            last_heartbeat = time.monotonic()
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue
                        if not isinstance(message, str):
                            continue
                        if "InvalidPassword" in message:
                            room_id = current_room["id"] if current_room else ""
                            raise RuntimeError(f"房间 {room_id} 密码错误")
                        if message.startswith("jump{"):
                            self.joined_room_id = ""
                            try:
                                jump = json.loads(message[4:])
                            except (TypeError, ValueError):
                                jump = {}
                            jump_room = str(jump.get("r", "")) if isinstance(jump, dict) else ""
                            jump_line = str(jump.get("l", "")) if isinstance(jump, dict) else ""
                            elapsed = time.monotonic() - join_sent_at if join_sent_at else 0.0
                            self.events.put((
                                "room_diag",
                                f"线路 {server_name} 收到 jump：房间 {jump_room or '(未知)'}，"
                                f"线路号 {jump_line or '(未知)'}，本次耗时 {elapsed:.2f}s。",
                            ))
                            redirect_room_id = jump_room or (current_room["id"] if current_room else "")
                            try:
                                target_index = room_server_index_for_line(int(jump_line))
                            except ValueError:
                                target_index = None
                            if target_index is not None:
                                pinned_server_index = target_index
                            server_index = (
                                target_index if target_index is not None
                                else next_room_server_index(server_index)
                            )
                            redirected = True
                            self.events.put(("room_status", "已确定房间线路，正在连接目标线路。" if target_index is not None else "当前线路无法进入房间，正在切换服务器。"))
                            break
                        if message.startswith("JoinRoom{"):
                            room_id = current_room["id"] if current_room else ""
                            if self.joined_room_id == room_id and not join_started:
                                continue
                            self.joined_room_id = room_id
                            pinned_server_index = server_index
                            redirect_room_id = ""
                            join_started = 0.0
                            elapsed = time.monotonic() - join_sent_at if join_sent_at else 0.0
                            for topic in ("Room", "Game", "Player", "RoomUsers"):
                                await ws.send(json.dumps({"c": "SO_o", "n": f"{topic}{room_id}"}))
                            await ws.send(json.dumps({"c": "JoinRoomDelay"}))
                            self.events.put((
                                "room_diag",
                                f"线路 {server_name} 入房成功：房间 {room_id}，"
                                f"第 {join_attempt} 次，耗时 {elapsed:.2f}s。",
                            ))
                            self.events.put(("room_joined", room_id))
                            continue
                        parsed = parse_room_say(message)
                        if parsed and current_room:
                            user_id, user_name, content = parsed
                            target = self.target_player
                            if target and target in {user_id, user_name}:
                                self.events.put(("room_question", (user_id, user_name, content)))
            except RuntimeError:
                raise
            except Exception as exc:
                if not stop_event.is_set():
                    self.events.put((
                        "room_diag",
                        f"线路 {server_name} 连接关闭或异常：{type(exc).__name__}: {exc}",
                    ))
                    self.events.put(("room_status", f"连接中断，正在重连：{exc}"))
            if stop_event.is_set():
                return
            if not redirected:
                server_index = next_room_server_index(server_index, pinned_server_index)
                await asyncio.sleep(2)


class RegionOverlay:
    def __init__(self, app: "QuizApp", x: int, y: int, w: int, h: int):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.25)
        self.window.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas = tk.Canvas(self.window, bg="#ffffff", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.draw)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.mode = "move"
        self.start = (0, 0, x, y, w, h)

    def draw(self, _event=None):
        self.canvas.delete("all")
        w, h = self.window.winfo_width(), self.window.winfo_height()
        self.canvas.create_rectangle(3, 3, max(4, w - 3), max(4, h - 3), outline="#ff2d20", width=5)
        self.canvas.create_rectangle(max(4, w - 22), max(4, h - 22), w - 4, h - 4, fill="#ff2d20", outline="")

    def press(self, event):
        x, y = self.window.winfo_x(), self.window.winfo_y()
        w, h = self.window.winfo_width(), self.window.winfo_height()
        self.mode = "resize" if event.x >= w - 30 and event.y >= h - 30 else "move"
        self.start = (event.x_root, event.y_root, x, y, w, h)

    def move(self, event):
        sx, sy, x, y, w, h = self.start
        dx, dy = event.x_root - sx, event.y_root - sy
        if self.mode == "resize":
            self.window.geometry(f"{max(160, w + dx)}x{max(80, h + dy)}+{x}+{y}")
        else:
            self.window.geometry(f"{w}x{h}+{x + dx}+{y + dy}")

    def release(self, _event):
        self.app.q_x.set(str(self.window.winfo_x()))
        self.app.q_y.set(str(self.window.winfo_y()))
        self.app.q_w.set(str(self.window.winfo_width()))
        self.app.q_h.set(str(self.window.winfo_height()))
        self.app.save_region()

    def close(self):
        self.app.overlay = None
        self.window.destroy()


class QuizApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("智能问答助手")
        window_height = min(780, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"1000x{window_height}")
        self.root.minsize(960, 680)
        self.config = load_config()
        self.windows: list[BrowserWindow] = []
        self.overlay: Optional[RegionOverlay] = None
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.send_lock = threading.Lock()
        self.settings_lock = threading.Lock()
        self.live_settings = self.config
        self.click_ready = threading.Event()
        self.click_ready.set()
        self.events: queue.Queue = queue.Queue()
        self.running = False
        self.active_workers: set[str] = set()
        self.region_touched = CONFIG_PATH.exists()
        self.lock_state = bool(self.config.get("lock_enabled", False))
        self.lock_target = saved_window(self.config)
        self.lock_busy = False
        self.lock_enabled = tk.BooleanVar(value=self.lock_state)
        self.model = tk.StringVar(value=str(self.config["model"]))
        self.base_url = tk.StringVar(value=str(self.config["base_url"]))
        self.api_key = tk.StringVar(value=str(self.config["api_key"]))
        self.gemini_base_url = tk.StringVar(value=str(self.config["gemini_base_url"]))
        self.gemini_model = tk.StringVar(value=str(self.config["gemini_model"]))
        self.gemini_api_key = tk.StringVar(value=str(self.config["gemini_api_key"]))
        self.knowledge_enabled = tk.BooleanVar(value=bool(self.config["knowledge_enabled"]))
        self.knowledge_base_id = tk.StringVar(value=str(self.config["knowledge_base_id"]))
        self.web_search_enabled = tk.BooleanVar(value=bool(self.config["web_search_enabled"]))
        self.google_search_enabled = tk.BooleanVar(value=bool(self.config["google_search_enabled"]))
        self.dry_run_enabled = tk.BooleanVar(value=bool(self.config["dry_run_enabled"]))
        self.answer_mode = tk.StringVar(value=str(self.config["answer_mode"]))
        self.bot_config_path = tk.StringVar(value=str(self.config["bot_config_path"]))
        room = self.config["room"]
        self.room_id = tk.StringVar(value=str(room["id"]))
        self.room_password = tk.StringVar(value=str(room["password"]))
        self.room_player = tk.StringVar(value=str(room["player"]))
        self.room_status = tk.StringVar(value="未连接")
        self.room_join_pending = False
        self.room_client = RoomClient(self.events)
        self.room_questions: queue.Queue = queue.Queue(maxsize=1)
        self.active_mode: Optional[str] = None
        self.bot_config_window: Optional[tk.Toplevel] = None
        self.test_question = tk.StringVar()
        self.test_result = tk.StringVar(value="尚未测试")
        self.test_qa_window: Optional[tk.Toplevel] = None
        self.test_qa_button = None
        q = self.config["question"]
        self.q_x, self.q_y = tk.StringVar(value=str(q["x"])), tk.StringVar(value=str(q["y"]))
        self.q_w, self.q_h = tk.StringVar(value=str(q["w"])), tk.StringVar(value=str(q["h"]))
        inp = self.config["input"]
        self.input_x = tk.StringVar(value=str(inp["x_percent"]))
        self.input_y = tk.StringVar(value=str(inp["y_percent"]))
        send = self.config["send"]
        self.send_x = tk.StringVar(value=str(send["x_percent"]))
        self.send_y = tk.StringVar(value=str(send["y_percent"]))
        self.click_positions = (
            float(inp["x_percent"]), float(inp["y_percent"]),
            float(send["x_percent"]), float(send["y_percent"]),
        )
        self.point_markers: list[tk.Toplevel] = []
        self.marker_timer = None
        self.markers_visible = False
        self.markers_cleared = threading.Event()
        self.markers_cleared.set()
        self.pick_kind = "input"
        self.threshold = tk.StringVar(value=str(self.config["threshold"]))
        self.poll_seconds = tk.StringVar(value=str(self.config["poll_seconds"]))
        self.status = tk.StringVar(value="就绪")
        self.browser_choice = tk.StringVar()
        self.page_view = tk.StringVar(value="answer")
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.refresh_windows()
        self.root.after(100, self.pump_events)
        self.root.after(300, self.restore_startup_window)
        self.root.after(2300, self.enforce_lock)
        if self.config.get("knowledge_enabled"):
            threading.Thread(target=self._warm_local_knowledge, daemon=True).start()

    def _warm_local_knowledge(self):
        started = time.perf_counter()
        try:
            count = LOCAL_KNOWLEDGE.ensure_loaded()
            self.events.put((
                "log",
                f"本地知识库已就绪：23 份 PDF + 2 份 Markdown，{count} 个文本块，"
                f"耗时 {time.perf_counter() - started:.2f}s。",
            ))
        except Exception as exc:
            self.events.put(("log", f"本地知识库预加载失败，将使用远端知识库：{exc}"))

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        background = "#ffffff"
        text = "#182230"
        muted = "#667085"
        accent = "#175cd3"
        border = "#d7dde5"
        self.root.configure(background=background)
        style.configure("TButton", padding=(7, 3))

        def button(parent, label, command, primary=False):
            return tk.Button(
                parent, text=label, command=command,
                background="#eef2f6", activebackground="#dde3ea",
                foreground=text, activeforeground=text,
                relief="flat", borderwidth=0, highlightthickness=0,
                padx=12, pady=4, cursor="pointinghand",
                font=("Helvetica", 11, "bold" if primary else "normal"),
            )

        outer = tk.Frame(self.root, padx=12, pady=10, background=background)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, background=background)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="智能问答助手", background=background, foreground=text, font=("Helvetica", 17, "bold")).pack(side="left")
        tk.Label(header, textvariable=self.status, background=background, foreground=accent).pack(side="right", pady=(4, 0))

        tab_bar = tk.Frame(outer, background=background)
        tab_bar.pack(fill="x", pady=(0, 6))
        pages = tk.Frame(outer, background=background)
        pages.pack(fill="x", pady=(0, 8))
        pages.columnconfigure(0, weight=1)
        answer_tab = tk.Frame(pages, padx=8, pady=8, background=background)
        calibration_tab = tk.Frame(pages, padx=8, pady=8, background=background)
        answer_tab.grid(row=0, column=0, sticky="nsew")
        calibration_tab.grid(row=0, column=0, sticky="nsew")

        tab_buttons = {}

        def show_page(page):
            self.page_view.set(page)
            (answer_tab if page == "answer" else calibration_tab).tkraise()
            for value, tab in tab_buttons.items():
                tab.configure(
                    foreground=accent if value == page else muted,
                    font=("Helvetica", 12, "bold" if value == page else "normal"),
                )

        for label, value in (("答题", "answer"), ("页面校准", "calibration")):
            tab = tk.Label(
                tab_bar, text=label, background=background,
                foreground=accent if value == "answer" else muted,
                font=("Helvetica", 12, "bold" if value == "answer" else "normal"),
                padx=10, pady=4, cursor="pointinghand",
            )
            tab.bind("<Button-1>", lambda _event, selected=value: show_page(selected))
            tab.pack(side="left")
            tab_buttons[value] = tab
        show_page("answer")

        browser_box = tk.LabelFrame(calibration_tab, text="浏览器窗口", padx=10, pady=8, background=background, foreground=text, font=("Helvetica", 11, "bold"), relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=border)
        browser_box.pack(fill="x", pady=(0, 5))
        browser_box.columnconfigure(0, weight=1)
        ttk.Combobox(browser_box, textvariable=self.browser_choice, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.browser_combo = browser_box.winfo_children()[0]
        self.browser_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_window_selected())
        button(browser_box, "刷新窗口", self.refresh_windows).grid(row=0, column=1, padx=3)
        button(browser_box, "保存当前位置", self.save_window_position).grid(row=0, column=2, padx=3)
        button(browser_box, "恢复固定位置", self.restore_window).grid(row=0, column=3, padx=3)
        tk.Checkbutton(browser_box, text="持续锁定", variable=self.lock_enabled, command=self.toggle_lock, background=background, activebackground=background, highlightthickness=0).grid(row=0, column=4, padx=(10, 0))
        self.window_note = tk.Label(browser_box, text="需要 macOS 辅助功能权限", background=background, foreground=muted)
        self.window_note.grid(row=1, column=0, columnspan=5, sticky="w", pady=(3, 0))

        config_box = tk.LabelFrame(answer_tab, text="模型配置", padx=10, pady=8, background=background, foreground=text, font=("Helvetica", 11, "bold"), relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=border)
        config_box.pack(fill="x", pady=(0, 5))
        config_box.columnconfigure(1, weight=1)
        config_box.columnconfigure(3, weight=1)
        self.add_entry(config_box, 0, 0, "Model", self.model)
        self.add_entry(config_box, 0, 2, "API Key", self.api_key, show="*")
        self.add_entry(config_box, 1, 0, "Base URL", self.base_url, columnspan=3)
        tk.Label(config_box, text="知识库 ID", background=background, foreground=text).grid(row=2, column=0, sticky="e", padx=(0, 6), pady=1)
        knowledge_entry = ttk.Entry(config_box, textvariable=self.knowledge_base_id)
        knowledge_entry.grid(row=2, column=1, sticky="ew", pady=1)
        knowledge_entry.bind("<FocusOut>", lambda _event: self.save_settings(quiet=True))
        tk.Checkbutton(config_box, text="启用知识库", variable=self.knowledge_enabled, command=self.apply_tool_settings, background=background, activebackground=background, highlightthickness=0).grid(row=2, column=2, sticky="w", padx=(6, 0))
        tk.Checkbutton(config_box, text="启用联网搜索", variable=self.web_search_enabled, command=self.apply_tool_settings, background=background, activebackground=background, highlightthickness=0).grid(row=2, column=3, sticky="w")
        self.add_entry(config_box, 3, 0, "Gemini Base URL", self.gemini_base_url, columnspan=3)
        self.add_entry(config_box, 4, 0, "Gemini Model", self.gemini_model)
        self.add_entry(config_box, 4, 2, "Gemini API Key", self.gemini_api_key, show="*")
        button(config_box, "保存配置", self.save_settings).grid(row=0, column=4, rowspan=5, padx=(8, 0))

        room_box = tk.LabelFrame(answer_tab, text="答题模式", padx=10, pady=8, background=background, foreground=text, font=("Helvetica", 11, "bold"), relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=border)
        room_box.pack(fill="x", pady=(0, 5))
        tk.Radiobutton(room_box, text="页面题目", variable=self.answer_mode, value="screen", command=self.apply_answer_mode, background=background, activebackground=background, highlightthickness=0).grid(row=0, column=0, padx=(0, 8))
        tk.Radiobutton(room_box, text="房间发言", variable=self.answer_mode, value="room", command=self.apply_answer_mode, background=background, activebackground=background, highlightthickness=0).grid(row=0, column=1, padx=(0, 12))
        tk.Radiobutton(room_box, text="并行运行", variable=self.answer_mode, value="both", command=self.apply_answer_mode, background=background, activebackground=background, highlightthickness=0).grid(row=0, column=2, padx=(0, 12))
        self.room_controls = tk.Frame(room_box, background=background)
        self.room_controls.grid(row=1, column=0, columnspan=8, sticky="ew")
        self.room_controls.columnconfigure(5, weight=1)
        tk.Checkbutton(
            self.room_controls, text="收到题目并行调用主模型 + Gemini 搜索",
            variable=self.google_search_enabled, command=self.apply_google_search_setting,
            background=background, activebackground=background, highlightthickness=0,
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        self.room_connect_button = button(self.room_controls, "连接/登录", self.connect_bot)
        self.room_connect_button.grid(row=0, column=4, padx=(0, 6), sticky="e")
        self.room_join_button = button(self.room_controls, "加入房间", self.join_room)
        self.room_join_button.grid(row=0, column=5, sticky="e")
        tk.Label(self.room_controls, text="房间号", background=background, foreground=text).grid(row=1, column=0, sticky="e", pady=(5, 0))
        ttk.Entry(self.room_controls, textvariable=self.room_id, width=9).grid(row=1, column=1, padx=(4, 8), pady=(5, 0), sticky="w")
        tk.Label(self.room_controls, text="密码", background=background, foreground=text).grid(row=1, column=2, sticky="e", pady=(5, 0))
        ttk.Entry(self.room_controls, textvariable=self.room_password, width=10).grid(row=1, column=3, padx=(4, 8), pady=(5, 0), sticky="w")
        tk.Label(self.room_controls, text="玩家 ID/昵称", background=background, foreground=text).grid(row=1, column=4, sticky="e", pady=(5, 0))
        ttk.Entry(self.room_controls, textvariable=self.room_player).grid(row=1, column=5, sticky="ew", padx=(4, 0), pady=(5, 0))
        tk.Label(self.room_controls, text="机器人配置", background=background, foreground=text).grid(row=2, column=0, sticky="e", pady=(5, 0), padx=(0, 6))
        ttk.Entry(self.room_controls, textvariable=self.bot_config_path).grid(row=2, column=1, columnspan=4, sticky="ew", pady=(5, 0), padx=(0, 8))
        config_actions = tk.Frame(self.room_controls, background=background)
        config_actions.grid(row=2, column=5, pady=(5, 0), sticky="e")
        self.refresh_login_button = button(config_actions, "更新登录", self.refresh_bot_login)
        self.refresh_login_button.pack(side="left", padx=(0, 4))
        button(config_actions, "编辑 JSON", self.edit_bot_config).pack(side="left")
        tk.Label(self.room_controls, textvariable=self.room_status, foreground=accent, background=background, wraplength=860).grid(row=3, column=0, columnspan=6, sticky="w", pady=(5, 0))

        tune = tk.LabelFrame(calibration_tab, text="题区与点击位置", padx=10, pady=8, background=background, foreground=text, font=("Helvetica", 11, "bold"), relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=border)
        tune.pack(fill="x", pady=(0, 5))
        for i, (label, var) in enumerate((("题区 X", self.q_x), ("题区 Y", self.q_y), ("宽", self.q_w), ("高", self.q_h), ("输入框 X%", self.input_x), ("输入框 Y%", self.input_y))):
            row, col = divmod(i, 6)
            tk.Label(tune, text=label, background=background, foreground=text).grid(row=0, column=col, padx=(0 if col == 0 else 8, 3), sticky="e")
            entry = ttk.Entry(tune, textvariable=var, width=8)
            entry.grid(row=1, column=col, padx=(0 if col == 0 else 8, 3), sticky="ew")
            if label.startswith("输入框"):
                entry.bind("<FocusIn>", self.begin_click_edit)
                entry.bind("<FocusOut>", self.finish_click_edit)
            else:
                entry.bind("<FocusOut>", self.autosave_positions)
        button(tune, "显示红框", self.show_overlay).grid(row=2, column=0, columnspan=2, pady=(6, 0), sticky="ew")
        button(tune, "拾取输入框", self.pick_input).grid(row=2, column=2, columnspan=2, pady=(6, 0), padx=4, sticky="ew")
        button(tune, "拾取发送按钮", self.pick_send).grid(row=2, column=4, columnspan=2, pady=(6, 0), sticky="ew")
        tk.Label(tune, text="发送按钮 X%", background=background, foreground=text).grid(row=3, column=0, sticky="e", pady=(4, 0))
        send_x_entry = ttk.Entry(tune, textvariable=self.send_x, width=8)
        send_x_entry.grid(row=3, column=1, sticky="ew", pady=(4, 0))
        send_x_entry.bind("<FocusIn>", self.begin_click_edit)
        send_x_entry.bind("<FocusOut>", self.finish_click_edit)
        tk.Label(tune, text="发送按钮 Y%", background=background, foreground=text).grid(row=3, column=2, sticky="e", pady=(4, 0))
        send_y_entry = ttk.Entry(tune, textvariable=self.send_y, width=8)
        send_y_entry.grid(row=3, column=3, sticky="ew", pady=(4, 0))
        send_y_entry.bind("<FocusIn>", self.begin_click_edit)
        send_y_entry.bind("<FocusOut>", self.finish_click_edit)
        button(tune, "显示点击标记", self.show_click_markers).grid(row=3, column=4, columnspan=2, sticky="ew", padx=(6, 0), pady=(4, 0))

        run_box = tk.Frame(answer_tab, padx=2, pady=4, background=background)
        run_box.pack(fill="x", pady=(0, 5))
        self.screen_poll_controls = tk.Frame(run_box, background=background)
        self.screen_poll_controls.pack(side="left")
        tk.Label(self.screen_poll_controls, text="变化阈值", background=background, foreground=text).pack(side="left")
        ttk.Entry(self.screen_poll_controls, textvariable=self.threshold, width=8).pack(side="left", padx=(5, 14))
        tk.Label(self.screen_poll_controls, text="轮询秒数", background=background, foreground=text).pack(side="left")
        ttk.Entry(self.screen_poll_controls, textvariable=self.poll_seconds, width=8).pack(side="left", padx=(5, 14))
        self.start_button = button(run_box, "开始答题", self.start, primary=True)
        self.start_button.pack(side="left", padx=(6, 4))
        button(run_box, "测试问答", self.show_test_qa).pack(side="left", padx=(0, 4))
        self.test_send_button = button(run_box, "测试发送", self.test_send)
        self.test_send_button.pack(side="left", padx=(0, 4))
        tk.Checkbutton(run_box, text="仅回答，不发送", variable=self.dry_run_enabled, command=self.apply_dry_run_setting, background=background, activebackground=background, highlightthickness=0).pack(side="left", padx=(4, 4))
        self.stop_button = button(run_box, "停止", self.stop)
        self.stop_button.configure(state="disabled")
        self.stop_button.pack(side="left")
        if self.answer_mode.get() in {"screen", "both"}:
            self.screen_poll_controls.pack(side="left", before=self.start_button)
        else:
            self.screen_poll_controls.pack_forget()
        if self.answer_mode.get() in {"room", "both"}:
            self.room_controls.grid()
        else:
            self.room_controls.grid_remove()

        log_box = tk.LabelFrame(outer, text=f"运行日志  ({LOG_PATH})", padx=8, pady=7, background=background, foreground=text, font=("Helvetica", 11, "bold"), relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=border)
        log_box.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_box, height=10, wrap="word", state="disabled", font=("Menlo", 10),
            background="#ffffff", foreground=text, selectbackground="#cfe1ff",
            relief="flat", highlightthickness=1, highlightbackground="#d7dde5",
            padx=7, pady=6,
        )
        self.log_text.tag_configure("answer", foreground="#d93025")
        scroll = ttk.Scrollbar(log_box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    @staticmethod
    def add_entry(parent, row, column, label, variable, show=None, columnspan=1):
        tk.Label(parent, text=label, background="#ffffff", foreground="#182230").grid(row=row, column=column, sticky="e", padx=(0, 6), pady=1)
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.grid(row=row, column=column + 1, columnspan=columnspan, sticky="ew", pady=1)

    def apply_answer_mode(self):
        if self.answer_mode.get() in {"screen", "both"}:
            self.screen_poll_controls.pack(side="left", before=self.start_button)
        else:
            self.screen_poll_controls.pack_forget()
        if self.answer_mode.get() in {"room", "both"}:
            self.room_controls.grid()
        else:
            self.room_controls.grid_remove()
        self.save_settings(quiet=True)

    def current_window(self) -> Optional[BrowserWindow]:
        try:
            return self.windows[self.browser_combo.current()]
        except (AttributeError, IndexError):
            return None

    def refresh_windows(self):
        self.windows = chrome_windows()
        labels = [w.label for w in self.windows]
        self.browser_combo.configure(values=labels)
        if labels:
            saved = self.lock_target
            match = next((i for i, w in enumerate(self.windows) if saved and same_browser_window(saved, w)), None)
            if match is not None:
                self.browser_combo.current(match)
            elif self.browser_combo.current() < 0 or self.browser_combo.current() >= len(labels):
                self.browser_combo.current(0)
            self.browser_choice.set(labels[self.browser_combo.current()])
            if not self.region_touched:
                self.set_default_region(self.windows[self.browser_combo.current()])
            saved_text = f"；固定位置 {saved.x},{saved.y} {saved.w}x{saved.h}" if saved else "；尚未保存固定位置"
            self.window_note.configure(text=f"找到 {len(labels)} 个浏览器窗口{saved_text}")
        else:
            self.browser_choice.set("")
            self.window_note.configure(text="没有找到可见的 Chrome/Chromium/Edge 窗口。")

    def on_window_selected(self):
        self.region_touched = True

    def set_default_region(self, window: BrowserWindow):
        self.q_x.set(str(window.x + round(window.w * 0.02)))
        self.q_y.set(str(window.y + round(window.h * 0.405)))
        self.q_w.set(str(round(window.w * 0.96)))
        self.q_h.set(str(round(window.h * 0.20)))

    def read_int(self, variable, name, minimum=0) -> int:
        try:
            value = int(float(variable.get()))
        except ValueError as exc:
            raise ValueError(f"{name} 必须是数字") from exc
        if value < minimum:
            raise ValueError(f"{name} 不能小于 {minimum}")
        return value

    def read_float(self, variable, name, minimum=0.0) -> float:
        try:
            value = float(variable.get())
        except ValueError as exc:
            raise ValueError(f"{name} 必须是数字") from exc
        if value < minimum:
            raise ValueError(f"{name} 不能小于 {minimum}")
        return value

    def read_percent(self, variable, name) -> float:
        value = self.read_float(variable, name)
        if value > 100:
            raise ValueError(f"{name} 不能大于 100")
        return value

    def settings(self) -> dict:
        knowledge_base_id = self.knowledge_base_id.get().strip()
        if self.knowledge_enabled.get() and not knowledge_base_id:
            raise ValueError("启用知识库时必须填写知识库 ID")
        return {
            "model": self.model.get().strip(),
            "base_url": self.base_url.get().strip(),
            "api_key": self.api_key.get().strip(),
            "gemini_base_url": self.gemini_base_url.get().strip(),
            "gemini_model": self.gemini_model.get().strip(),
            "gemini_api_key": self.gemini_api_key.get().strip(),
            "knowledge_enabled": bool(self.knowledge_enabled.get()),
            "knowledge_base_id": knowledge_base_id,
            "web_search_enabled": bool(self.web_search_enabled.get()),
            "google_search_enabled": bool(self.google_search_enabled.get()),
            "dry_run_enabled": bool(self.dry_run_enabled.get()),
            "answer_mode": self.answer_mode.get(),
            "bot_config_path": self.bot_config_path.get().strip(),
            "room": {
                "id": self.room_id.get().strip(),
                "password": self.room_password.get(),
                "player": self.room_player.get().strip(),
            },
            "question": {"x": self.read_int(self.q_x, "题区 X"), "y": self.read_int(self.q_y, "题区 Y"), "w": self.read_int(self.q_w, "题区宽", 80), "h": self.read_int(self.q_h, "题区高", 40)},
            "input": {"x_percent": self.read_percent(self.input_x, "输入框 X%"), "y_percent": self.read_percent(self.input_y, "输入框 Y%")},
            "send": {"x_percent": self.read_percent(self.send_x, "发送按钮 X%"), "y_percent": self.read_percent(self.send_y, "发送按钮 Y%")},
            "threshold": self.read_float(self.threshold, "变化阈值", 0.1),
            "poll_seconds": self.read_float(self.poll_seconds, "轮询秒数", 0.01),
            "lock_enabled": self.lock_state,
            "window": window_as_dict(self.lock_target) if self.lock_target else None,
        }

    def save_settings(self, quiet=False):
        try:
            settings = self.settings()
            save_config(settings)
        except (OSError, ValueError) as exc:
            if not quiet:
                messagebox.showerror("保存失败", str(exc))
            return False
        self.click_positions = (
            settings["input"]["x_percent"], settings["input"]["y_percent"],
            settings["send"]["x_percent"], settings["send"]["y_percent"],
        )
        with self.settings_lock:
            self.live_settings = settings
        if not quiet:
            self.log("配置已保存：" + str(CONFIG_PATH))
        return True

    def apply_tool_settings(self):
        if not self.save_settings():
            with self.settings_lock:
                previous = self.live_settings.copy()
            self.knowledge_enabled.set(previous["knowledge_enabled"])
            self.web_search_enabled.set(previous["web_search_enabled"])
            return
        tools = [name for enabled, name in (
            (self.knowledge_enabled.get(), "知识库"),
            (self.web_search_enabled.get(), "联网搜索"),
        ) if enabled]
        self.log("回答工具已立即更新：" + (" + ".join(tools) if tools else "未启用"))
        if self.knowledge_enabled.get():
            threading.Thread(target=self._warm_local_knowledge, daemon=True).start()

    def apply_dry_run_setting(self):
        if self.save_settings(quiet=True):
            self.log("真实答题发送已立即" + ("关闭；仅记录答案" if self.dry_run_enabled.get() else "启用"))

    def apply_google_search_setting(self):
        if self.save_settings(quiet=True):
            self.log("房间题目 Gemini Google Search 已" + ("启用" if self.google_search_enabled.get() else "关闭"))

    @staticmethod
    def validate_room(settings: dict, require_player: bool = False) -> None:
        room = settings["room"]
        if not room["id"].isdigit():
            raise ValueError("房间号必须是数字")
        if not settings["bot_config_path"]:
            raise ValueError("请填写机器人配置路径")
        if require_player and not room["player"]:
            raise ValueError("房间模式必须填写指定玩家 ID 或昵称")

    def start_room_client(self, settings: dict) -> None:
        self.validate_room(settings)
        self.room_client.join(settings)
        self.room_join_pending = True
        self.room_connect_button.configure(state="disabled")
        self.room_join_button.configure(state="disabled")
        self.room_status.set("正在加入房间...")
        self.log(f"机器人正在加入房间 {settings['room']['id']}。")

    def connect_bot(self):
        if not self.save_settings():
            return
        with self.settings_lock:
            settings = self.live_settings.copy()
        if not settings["bot_config_path"]:
            messagebox.showerror("连接失败", "请填写机器人配置路径")
            return
        try:
            self.room_client.connect(settings)
        except RuntimeError as exc:
            messagebox.showerror("连接失败", str(exc))
            return
        self.room_join_pending = False
        self.room_connect_button.configure(state="disabled")
        self.room_join_button.configure(state="disabled")
        self.room_status.set("正在连接/登录...")
        self.log("机器人正在连接并登录。")

    def join_room(self):
        if not self.save_settings():
            return
        with self.settings_lock:
            settings = self.live_settings.copy()
        try:
            self.start_room_client(settings)
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("加入房间失败", str(exc))

    def refresh_bot_login(self):
        if not self.save_settings(quiet=True):
            return
        config_path = Path(self.bot_config_path.get().strip()).expanduser().resolve()
        project_dir = config_path.parent
        script = project_dir / "tools/ws_capture.py"
        python = project_dir / "venv/bin/python"
        if not script.exists():
            messagebox.showerror("更新登录失败", f"找不到 {script}")
            return
        if not python.exists():
            python = Path(sys.executable)
        self.refresh_login_button.configure(state="disabled")
        self.room_status.set("等待浏览器登录并同步参数...")
        self.log("已打开专用 Chrome；首次使用请登录并进入游戏，程序会自动更新登录参数。")

        def run():
            try:
                result = subprocess.run(
                    [str(python), str(script), "--sync-login", "--no-ai", "--config", str(config_path)],
                    cwd=project_dir, text=True, capture_output=True, timeout=150,
                )
                if result.returncode:
                    detail = (result.stderr or result.stdout or "登录参数同步失败").strip()[-500:]
                    raise RuntimeError(detail)
                self.events.put(("bot_login_refreshed", ""))
            except Exception as exc:
                self.events.put(("bot_login_refresh_error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def edit_bot_config(self):
        if self.bot_config_window and self.bot_config_window.winfo_exists():
            self.bot_config_window.deiconify()
            self.bot_config_window.lift()
            return
        path = Path(self.bot_config_path.get().strip()).expanduser()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("读取配置失败", f"无法读取 {path}: {exc}")
            return
        try:
            content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
        except ValueError:
            pass

        window = tk.Toplevel(self.root)
        window.title("编辑机器人 JSON 配置")
        window.geometry("760x560")
        window.minsize(560, 400)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=str(path), foreground="#666").pack(anchor="w", pady=(0, 6))
        editor = ScrolledText(frame, wrap="word", font=("Menlo", 11), undo=True)
        editor.insert("1.0", content)
        editor.pack(fill="both", expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))

        def close():
            window.destroy()
            self.bot_config_window = None

        def save():
            try:
                data = json.loads(editor.get("1.0", "end-1c"))
                if not isinstance(data, dict):
                    raise ValueError("JSON 顶层必须是对象")
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                path.chmod(0o600)
            except ValueError as exc:
                messagebox.showerror("JSON 格式错误", str(exc), parent=window)
                return
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=window)
                return
            self.log(f"机器人配置已保存：{path}")
            close()

        ttk.Button(buttons, text="取消", command=close).pack(side="right")
        ttk.Button(buttons, text="保存", command=save).pack(side="right", padx=(0, 6))
        window.protocol("WM_DELETE_WINDOW", close)
        self.bot_config_window = window

    def show_test_qa(self):
        if self.test_qa_window and self.test_qa_window.winfo_exists():
            self.test_qa_window.deiconify()
            self.test_qa_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("测试问答")
        window.geometry("720x180")
        window.minsize(560, 160)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="输入问题").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(frame, textvariable=self.test_question)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(5, 10))
        entry.bind("<Return>", lambda _event: self.test_qa())
        self.test_qa_button = ttk.Button(frame, text="发送测试", command=self.test_qa)
        self.test_qa_button.grid(row=1, column=1, pady=(5, 10))
        ttk.Label(frame, textvariable=self.test_result, wraplength=670, foreground="#285f9e").grid(row=2, column=0, columnspan=2, sticky="w")
        self.test_qa_window = window
        entry.focus_set()

        def close():
            window.destroy()
            self.test_qa_window = None
            self.test_qa_button = None

        window.protocol("WM_DELETE_WINDOW", close)

    def test_qa(self):
        question = self.test_question.get().strip()
        if not question:
            messagebox.showwarning("没有问题", "请先输入要测试的问题")
            return
        if not self.save_settings(quiet=True):
            return
        with self.settings_lock:
            settings = self.live_settings.copy()
        if self.test_qa_button:
            self.test_qa_button.configure(state="disabled")
        self.test_result.set("正在请求...")
        self.log(f"测试问答：{question}")
        def run():
            try:
                use_gemini_search = settings.get("answer_mode") in {"room", "both"} and settings.get("google_search_enabled", False)
                if use_gemini_search:
                    answers, errors = call_room_answers(question, settings)
                    for label, exc in errors:
                        self.events.put(("log", f"{label}失败：{exc}"))
                    for label, answer, search_details in answers:
                        for detail in search_details:
                            self.events.put(("log", detail))
                        self.events.put(("log", f"{label}答案：{answer}"))
                        copy_answer(answer)
                        self.events.put(("log", f"已重新复制{label}答案：{answer}。"))
                    if not answers:
                        raise RuntimeError("主模型和 Gemini 都未返回答案")
                    self.events.put(("qa_test_done", "；".join(f"{label}：{value}" for label, value, _ in answers)))
                    return
                else:
                    answer, search_details = call_text_model(question, settings)
                for detail in search_details:
                    self.events.put(("log", detail))
                copy_answer(answer)
                self.events.put(("log", f"已重新复制主模型答案：{answer}。"))
                self.events.put(("qa_test_done", answer))
            except Exception as exc:
                self.events.put(("qa_test_error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def autosave_positions(self, _event=None):
        self.region_touched = True
        self.save_settings(quiet=True)

    def begin_click_edit(self, _event=None):
        self.click_ready.clear()

    def finish_click_edit(self, _event=None):
        self.autosave_positions()
        self.click_ready.set()

    def clear_click_markers(self):
        if self.marker_timer is not None:
            try:
                self.root.after_cancel(self.marker_timer)
            except tk.TclError:
                pass
        for marker in self.point_markers:
            try:
                marker.destroy()
            except tk.TclError:
                pass
        self.point_markers.clear()
        self.marker_timer = None
        self.markers_visible = False
        self.markers_cleared.set()

    def show_click_markers(self):
        if not self.save_settings(quiet=True):
            return
        window = self.current_window()
        if not window:
            messagebox.showwarning("没有窗口", "请先选择目标浏览器窗口")
            return
        fresh = next((w for w in chrome_windows() if w.owner == window.owner and w.title == window.title), window)
        self.clear_click_markers()
        self.markers_visible = True
        self.markers_cleared.clear()
        for color, point in (
            ("#1677ff", screen_point(fresh, self.click_positions[0], self.click_positions[1])),
            ("#e53935", screen_point(fresh, self.click_positions[2], self.click_positions[3])),
        ):
            marker = tk.Toplevel(self.root)
            marker.overrideredirect(True)
            marker.attributes("-topmost", True)
            marker.attributes("-alpha", 0.85)
            marker.attributes("-transparent", True)
            marker.configure(bg="systemTransparent")
            marker.geometry(f"12x12+{point[0] - 6}+{point[1] - 6}")
            canvas = tk.Canvas(marker, width=12, height=12, bg="systemTransparent", highlightthickness=0)
            canvas.create_oval(1, 1, 11, 11, fill=color, outline="white", width=1)
            canvas.pack()
            self.point_markers.append(marker)
        self.marker_timer = self.root.after(3000, self.clear_click_markers)
        self.log("已显示输入框和发送按钮标记（3 秒）")

    def toggle_lock(self):
        self.lock_state = bool(self.lock_enabled.get())
        if self.lock_state:
            if not self.lock_target:
                self.save_window_position()
            else:
                self.restore_window()
            self.log("持续锁定已启用")
        else:
            self.log("持续锁定已关闭")
        self.save_settings(quiet=True)

    def save_window_position(self):
        window = self.current_window()
        if not window:
            messagebox.showwarning("没有窗口", "请先刷新并选择一个浏览器窗口")
            return
        fresh = next((w for w in chrome_windows() if w.owner == window.owner and w.title == window.title), window)
        self.lock_target = fresh
        self.save_settings(quiet=True)
        self.window_note.configure(text=f"已保存固定位置：{fresh.x},{fresh.y} {fresh.w}x{fresh.h}")
        self.log(f"已保存窗口位置：{fresh.x},{fresh.y} {fresh.w}x{fresh.h}")

    def restore_window(self):
        if not self.lock_target:
            messagebox.showwarning("尚未保存", "请先选择窗口并点击“保存当前位置”")
            return
        ok, detail = set_window_bounds(self.lock_target)
        if ok:
            self.log(f"已恢复固定位置：{self.lock_target.x},{self.lock_target.y} {self.lock_target.w}x{self.lock_target.h}")
        else:
            self.log(f"恢复固定位置失败：{detail}")

    def restore_startup_window(self):
        if not self.lock_target or self.lock_busy:
            return
        self.lock_busy = True

        def apply():
            ok, detail = set_window_bounds(self.lock_target)
            if ok:
                self.events.put(("log", f"已从配置恢复窗口位置：{self.lock_target.x},{self.lock_target.y} {self.lock_target.w}x{self.lock_target.h}"))
            else:
                self.events.put(("log", f"启动时恢复窗口失败：{detail}"))
            self.lock_busy = False

        threading.Thread(target=apply, daemon=True).start()

    def enforce_lock(self):
        if self.lock_state and self.lock_target and not self.lock_busy:
            self.lock_busy = True

            def apply():
                ok, detail = set_window_bounds(self.lock_target)
                if not ok:
                    self.events.put(("log", f"持续锁定失败：{detail}"))
                self.lock_busy = False

            threading.Thread(target=apply, daemon=True).start()
        self.root.after(2000, self.enforce_lock)

    def show_overlay(self):
        if self.overlay:
            self.overlay.close()
        try:
            x, y = self.read_int(self.q_x, "题区 X"), self.read_int(self.q_y, "题区 Y")
            w, h = self.read_int(self.q_w, "题区宽", 80), self.read_int(self.q_h, "题区高", 40)
        except ValueError as exc:
            messagebox.showerror("校准失败", str(exc))
            return
        self.region_touched = True
        self.overlay = RegionOverlay(self, x, y, w, h)

    def save_region(self):
        self.region_touched = True
        if self.save_settings(quiet=True):
            self.log(f"已保存题区位置：{self.q_x.get()},{self.q_y.get()} {self.q_w.get()}x{self.q_h.get()}")

    def pick_input(self):
        self.pick_point("input")

    def pick_send(self):
        self.pick_point("send")

    def pick_point(self, kind: str):
        if pyautogui is None or not self.current_window():
            messagebox.showwarning("无法拾取", "需要先选择浏览器窗口")
            return
        self.pick_kind = kind
        self.click_ready.clear()
        label = "输入框中心" if kind == "input" else "发送按钮中心"
        self.status.set(f"请把鼠标移到{label}...")
        self.root.withdraw()
        self.root.after(2500, self.finish_pick_point)

    def finish_pick_point(self):
        picked = False
        try:
            pos = pyautogui.position()
            window = self.current_window()
            if window:
                if not (window.x <= pos.x <= window.x + window.w and window.y <= pos.y <= window.y + window.h):
                    self.log(f"拾取失败：鼠标 ({pos.x}, {pos.y}) 不在目标浏览器窗口内")
                    self.root.after(50, lambda: messagebox.showwarning("拾取失败", "鼠标不在目标浏览器窗口内，请重试。"))
                    return
                x_value = f"{(pos.x - window.x) * 100 / window.w:.1f}"
                y_value = f"{(pos.y - window.y) * 100 / window.h:.1f}"
                if self.pick_kind == "input":
                    self.input_x.set(x_value)
                    self.input_y.set(y_value)
                    label = "输入框"
                else:
                    self.send_x.set(x_value)
                    self.send_y.set(y_value)
                    label = "发送按钮"
                self.save_settings(quiet=True)
                self.log(f"已拾取{label}：屏幕坐标 ({pos.x}, {pos.y})")
                picked = True
        finally:
            self.root.deiconify()
            self.status.set("就绪")
            self.click_ready.set()
            if picked:
                self.root.after(100, self.show_click_markers)

    def start(self):
        if self.running:
            return
        try:
            settings = self.settings()
            if settings["answer_mode"] in {"room", "both"}:
                self.validate_room(settings, require_player=True)
            save_config(settings)
        except (OSError, ValueError) as exc:
            messagebox.showerror("配置无效", str(exc))
            return
        if settings["answer_mode"] in {"screen", "both"} and self.current_window() is None:
            messagebox.showwarning("没有窗口", "请先刷新并选择游戏浏览器窗口")
            return
        with self.settings_lock:
            self.live_settings = settings
        self.click_positions = (
            settings["input"]["x_percent"], settings["input"]["y_percent"],
            settings["send"]["x_percent"], settings["send"]["y_percent"],
        )
        needs_main_model = settings["answer_mode"] in {"screen", "room", "both"}
        if needs_main_model and (not self.model.get().strip() or not self.base_url.get().strip() or not self.api_key.get().strip()):
            messagebox.showwarning("配置不完整", "请填写 Model、Base URL 和 API key")
            return
        if settings["answer_mode"] in {"room", "both"} and settings.get("google_search_enabled") and not settings.get("gemini_api_key"):
            messagebox.showwarning("配置不完整", "已启用 Gemini Google Search，请填写 Gemini API Key")
            return
        if settings["answer_mode"] in {"room", "both"}:
            self.room_client.set_player(settings["room"]["player"])
        self.stop_event.clear()
        self.running = True
        self.active_mode = settings["answer_mode"]
        self.active_workers = set()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        if self.active_mode in {"room", "both"}:
            while not self.room_questions.empty():
                try:
                    self.room_questions.get_nowait()
                except queue.Empty:
                    break
            self.active_workers.add("room")
            self.log(f"房间模式已启动；只回答并复制 {settings['room']['player']} 的发言。")
        if self.active_mode in {"screen", "both"}:
            self.active_workers.add("screen")
            self.log("页面模式已启动；正在检查当前题区。" if self.active_mode == "both" else "开始运行；正在检查当前题区。")
        if self.active_mode == "room":
            self.status.set("房间模式：等待指定玩家发言")
        elif self.active_mode == "screen":
            self.status.set("运行中：检查当前题目")
        else:
            self.status.set("并行运行：页面题目 + 房间发言")
        workers = []
        if "room" in self.active_workers:
            workers.append(threading.Thread(target=self.room_answer_loop, daemon=True))
        if "screen" in self.active_workers:
            workers.append(threading.Thread(target=self.answer_loop, args=(settings, self.current_window()), daemon=True))
        for worker in workers:
            worker.start()

    def stop(self):
        self.stop_event.set()
        self.click_ready.set()
        if not self.running:
            return
        self.status.set("正在停止...")

    def enqueue_room_question(self, question: str) -> None:
        """只保留尚未开始处理的最新一题。"""
        while True:
            try:
                self.room_questions.get_nowait()
            except queue.Empty:
                break
        self.room_questions.put_nowait(question)

    def close_app(self):
        self.stop_event.set()
        self.room_client.stop()
        self.root.destroy()

    def test_send(self):
        if not self.save_settings(quiet=True):
            return
        window = self.current_window()
        if window is None:
            messagebox.showwarning("没有窗口", "请先刷新并选择目标浏览器窗口")
            return
        fresh = next((w for w in chrome_windows() if w.owner == window.owner and w.title == window.title), window)
        self.test_send_button.configure(state="disabled")
        self.log("测试发送：准备点击输入框、粘贴“测试”并点击发送按钮。")

        def run():
            try:
                with self.send_lock:
                    self.click_ready.wait()
                    if self.markers_visible:
                        self.events.put(("clear_markers", ""))
                        self.markers_cleared.wait(0.25)
                    positions = self.click_positions
                    self.events.put(("log", f"测试发送位置：输入 {positions[0]:.1f}%,{positions[1]:.1f}%；发送 {positions[2]:.1f}%,{positions[3]:.1f}%"))
                    paste_and_send("测试", fresh, *positions)
                self.events.put(("test_done", ""))
            except Exception as exc:
                self.events.put(("test_error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def answer_loop(self, settings: dict, win: BrowserWindow):
        try:
            if not win:
                raise RuntimeError("浏览器窗口已消失")
            q = settings["question"]
            get_frame = lambda: image_grab(q["x"], q["y"], q["w"], q["h"])
            self.events.put(("log", "截图方式：可见屏幕红框区域"))

            def submit(frame: Image.Image, status: str) -> None:
                self.events.put(("status", status))
                with self.settings_lock:
                    request_settings = self.live_settings.copy()
                enabled_tools = [name for enabled, name in (
                    (request_settings["knowledge_enabled"], "知识库"),
                    (request_settings["web_search_enabled"], "联网搜索"),
                ) if enabled]
                self.events.put(("log", "本题回答工具：" + (" + ".join(enabled_tools) if enabled_tools else "未启用")))
                answer, search_details = call_model(frame, request_settings)
                for detail in search_details:
                    self.events.put(("log", detail))
                self.events.put(("log", f"识别答案：{answer}"))
                with self.settings_lock:
                    dry_run = bool(self.live_settings.get("dry_run_enabled"))
                if dry_run:
                    copy_answer(answer)
                    self.events.put(("log", "仅回答模式已开启：答案已复制，本题不点击、不输入、不发送。"))
                    return
                while not self.click_ready.wait(0.05):
                    if self.stop_event.is_set():
                        return
                with self.send_lock:
                    with self.settings_lock:
                        dry_run = bool(self.live_settings.get("dry_run_enabled"))
                    if dry_run:
                        copy_answer(answer)
                        self.events.put(("log", "仅回答模式已在发送前开启：答案已复制，本题不点击、不输入、不发送。"))
                        return
                    if self.markers_visible:
                        self.events.put(("clear_markers", ""))
                        self.markers_cleared.wait(0.25)
                    positions = self.click_positions
                    self.events.put(("log", f"点击位置：输入 {positions[0]:.1f}%,{positions[1]:.1f}%；发送 {positions[2]:.1f}%,{positions[3]:.1f}%"))
                    paste_and_send(
                        answer, win,
                        *positions,
                    )
                self.events.put(("log", "已点击输入框、填入答案并点击发送按钮。"))

            first_image = get_frame()
            first_image.save(APP_DIR / "last_question_region.png")
            first_is_question = looks_like_question(first_image)
            self.events.put(("log", f"首帧像素判断：{'题目' if first_is_question else '非题目'}；截图已保存为 last_question_region.png"))
            if first_is_question:
                submit(first_image, "检测到当前题目，正在识别...")
                phase = "wait_result"
            else:
                phase = "wait_question"
            candidate = None
            while not self.stop_event.is_set():
                current_image = get_frame()
                current = frame_signature(current_image)
                is_question = looks_like_question(current_image)
                if phase == "wait_result":
                    if not is_question:
                        phase = "wait_question"
                        candidate = None
                        self.events.put(("status", "过渡中，等待下一题..."))
                elif is_question:
                    if candidate is not None and image_delta(current, candidate) < max(1.0, settings["threshold"] / 3):
                        submit(current_image, "检测到下一题，正在识别...")
                        phase = "wait_result"
                        candidate = None
                    else:
                        candidate = current
                else:
                    candidate = None
                time.sleep(settings["poll_seconds"])
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("worker_stopped", "screen"))

    def room_answer_loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    question = self.room_questions.get(timeout=0.2)
                except queue.Empty:
                    continue
                self.events.put(("status", "收到房间题目，正在回答..."))
                with self.settings_lock:
                    request_settings = self.live_settings.copy()
                try:
                    answer, search_details = call_text_model(question, request_settings)
                    for detail in search_details:
                        self.events.put(("log", detail))
                    self.events.put(("log", f"主模型答案：{answer}"))
                    copy_answer(answer)
                    if request_settings.get("google_search_enabled", False):
                        self.events.put(("log", f"已复制主模型答案：{answer}；Gemini 搜索在后台继续。"))
                    else:
                        self.events.put(("log", f"已复制主模型答案：{answer}。"))
                except Exception as exc:
                    self.events.put(("log", f"主模型失败：{exc}"))
                if request_settings.get("google_search_enabled", False):
                    threading.Thread(
                        target=self._room_gemini_answer,
                        args=(question, request_settings),
                        daemon=True,
                    ).start()
                self.events.put(("status", "房间模式：等待指定玩家发言"))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("worker_stopped", "room"))

    def _room_gemini_answer(self, question: str, settings: dict) -> None:
        try:
            answer, search_details = call_gemini_google_search(question, settings)
            for detail in search_details:
                self.events.put(("log", detail))
            self.events.put(("log", f"Gemini Google Search答案：{answer}"))
            copy_answer(answer)
            self.events.put(("log", f"已重新复制 Gemini 搜索答案：{answer}。"))
        except Exception as exc:
            self.events.put(("log", f"Gemini Google Search失败：{exc}"))

    def log(self, message: str):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}\n"
        try:
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line, "answer" if "答案：" in message else ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def pump_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.log(value)
                elif kind == "room_diag":
                    self.log(value)
                elif kind == "status":
                    self.status.set(value)
                elif kind == "room_status":
                    self.room_status.set(value)
                    if value.startswith(("连接中断", "加入房间超时", "当前线路无法进入房间")):
                        self.log(value)
                        self.room_connect_button.configure(state="normal")
                        self.room_join_button.configure(state="normal")
                elif kind == "room_connected":
                    self.room_status.set("已连接/登录")
                    self.room_connect_button.configure(state="normal")
                    self.room_join_button.configure(state="normal")
                    self.log("机器人 WebSocket 已连接并登录。")
                elif kind == "room_joined":
                    self.room_status.set(f"已加入房间 {value}")
                    self.room_connect_button.configure(state="normal")
                    self.room_join_button.configure(state="normal")
                    self.log(f"机器人已加入房间 {value}。")
                elif kind == "room_error":
                    self.room_status.set("连接失败")
                    self.room_connect_button.configure(state="normal")
                    self.room_join_button.configure(state="normal")
                    self.log("房间连接失败：" + value)
                    if self.running and self.active_mode in {"room", "both"}:
                        self.stop()
                    messagebox.showerror("房间连接失败", value)
                elif kind == "bot_login_refreshed":
                    self.refresh_login_button.configure(state="normal")
                    self.room_status.set("登录参数已更新")
                    self.log("机器人登录参数已自动更新，可以点击“连接/登录”。")
                elif kind == "bot_login_refresh_error":
                    self.refresh_login_button.configure(state="normal")
                    self.room_status.set("登录参数更新失败")
                    self.log("机器人登录参数更新失败：" + value)
                    messagebox.showerror("更新登录失败", value)
                elif kind == "room_question":
                    user_id, user_name, question = value
                    self.log(f"收到 {user_name}（{user_id}）发言：{question}")
                    if self.running and self.active_mode in {"room", "both"}:
                        question_length = len(question.strip())
                        if question_length < ROOM_QWEN_MIN_LENGTH:
                            self.log(f"房间模式：发言少于 {ROOM_QWEN_MIN_LENGTH} 个字，跳过回答和 Gemini Google Search。")
                            continue
                        with self.settings_lock:
                            google_search_enabled = bool(self.live_settings.get("google_search_enabled", False))
                        if google_search_enabled:
                            self.log("已加入 Gemini Google Search 回答队列。")
                        self.enqueue_room_question(question)
                elif kind == "error":
                    self.log("错误：" + value)
                    self.status.set("出错，已停止")
                    if self.running:
                        self.stop()
                    messagebox.showerror("答题停止", value)
                elif kind == "clear_markers":
                    self.clear_click_markers()
                elif kind == "test_done":
                    self.log("测试发送完成：已粘贴“测试”并点击发送按钮。")
                    self.test_send_button.configure(state="normal")
                elif kind == "test_error":
                    self.log("测试发送失败：" + value)
                    self.test_send_button.configure(state="normal")
                    messagebox.showerror("测试发送失败", value)
                elif kind == "qa_test_done":
                    self.test_result.set("答案：" + value)
                    self.log("测试问答答案：" + value)
                    if self.test_qa_button and self.test_qa_button.winfo_exists():
                        self.test_qa_button.configure(state="normal")
                elif kind == "qa_test_error":
                    self.test_result.set("测试失败：" + value)
                    self.log("测试问答失败：" + value)
                    if self.test_qa_button and self.test_qa_button.winfo_exists():
                        self.test_qa_button.configure(state="normal")
                    messagebox.showerror("测试问答失败", value)
                elif kind == "worker_stopped":
                    self.active_workers.discard(value)
                    if not self.active_workers:
                        self.running = False
                        self.active_mode = None
                        self.start_button.configure(state="normal")
                        self.stop_button.configure(state="disabled")
                        if self.status.get() == "正在停止...":
                            self.status.set("已停止")
        except queue.Empty:
            pass
        self.root.after(100, self.pump_events)


def self_test() -> None:
    import tempfile
    from PIL import ImageDraw

    a = Image.new("RGB", (120, 60), "white")
    b = a.copy()
    assert image_delta(frame_signature(a), frame_signature(b)) == 0
    ImageDraw.Draw(b).rectangle((20, 10, 100, 50), fill="black")
    assert image_delta(frame_signature(a), frame_signature(b)) > 7
    quiet = Image.new("RGB", (64, 32), "#e6e6e0")
    draw_quiet = ImageDraw.Draw(quiet)
    draw_quiet.text((10, 8), "题目", fill="#455b9a")
    busy = quiet.copy()
    draw = ImageDraw.Draw(busy)
    for y in range(17, 32, 3):
        draw.line((0, y, 63, y), fill=60, width=1)
    assert looks_like_question(quiet)
    assert not looks_like_question(busy)
    assert screen_point(BrowserWindow("Chrome", "test", 100, 50, 500, 800, 0), 25, 75) == (225, 650)
    search_url = google_search_url("谁是警察？")
    assert search_url.startswith("https://www.google.com/search?q=")
    assert "%E6%8E%A8%E7%90%86%E5%AD%A6%E9%99%A2" in search_url
    assert "+%E8%B0%81%E6%98%AF%E8%AD%A6%E5%AF%9F%EF%BC%9F" in search_url
    assert "只输出一个最适合填入的最短答案" in unquote_plus(search_url)
    assert google_search_bounds(1440, 900) == (960, 27, 1440, 873)
    saved_browser = BrowserWindow("Google Chrome", "推理学院", 0, 27, 500, 769, 0)
    decorated_browser = BrowserWindow("Google Chrome", "“推理学院”🔊", 0, 27, 500, 769, 0)
    assert normalized_window_title(decorated_browser.title) == "推理学院"
    assert same_browser_window(saved_browser, decorated_browser)
    assert not same_browser_window(saved_browser, BrowserWindow("Microsoft Edge", "推理学院", 0, 27, 500, 769, 0))
    test_settings = {
        "model": "qwen3.5-flash", "base_url": "https://example.test/v1",
        "knowledge_enabled": True, "knowledge_base_id": "kb-test", "web_search_enabled": True,
    }
    url, payload, responses_api = build_model_request("image-data", test_settings)
    assert url == "https://example.test/v1/responses"
    assert payload["tools"] == [
        {"type": "file_search", "vector_store_ids": ["kb-test"]},
        {"type": "web_search"},
    ]
    assert payload["tool_choice"] == {"type": "file_search"}
    assert payload["include"] == ["file_search_call.results"]
    assert "改用联网搜索" in payload["input"][0]["content"][0]["text"]
    assert "推理学院问题：请读取图片中的题目" in payload["input"][0]["content"][0]["text"]
    assert extract_answer({"output": [{"content": [{"type": "output_text", "text": "答案"}]}]}, responses_api) == "答案"
    assert extract_gemini_interaction_answer({"output_text": "兔子"}) == "兔子"
    assert extract_gemini_interaction_answer({"steps": [{"type": "model_output", "content": [{"type": "text", "text": "兔子"}]}]}) == "兔子"
    text_url, text_payload, text_responses_api = build_text_model_request("谁是警察？", test_settings)
    assert text_url == "https://example.test/v1/responses" and text_responses_api
    assert text_payload["tool_choice"] == {"type": "file_search"}
    assert "推理学院问题：谁是警察？" in text_payload["input"][0]["content"][0]["text"]
    searched = {
        "output": [
            {"type": "file_search_call", "queries": ["警察"], "results": [{"filename": "角色.pdf", "score": 0.9, "text": "资料"}]},
            {"content": [{"type": "output_text", "text": "答案"}]},
        ]
    }
    assert extract_answer(searched, True, True) == "答案"
    assert knowledge_search_details(searched) == [
        "知识库检索：查询 警察；命中 1 条",
        "知识库命中 1：角色.pdf；相似度 0.900；资料",
    ]
    try:
        extract_answer({"output": [{"type": "file_search_call", "results": []}]}, True, True)
    except RuntimeError as exc:
        assert "0 条资料" in str(exc)
    else:
        raise AssertionError("empty knowledge search must fail")
    plain_settings = {**test_settings, "knowledge_enabled": False, "web_search_enabled": False}
    text_url, text_payload, text_responses_api = build_text_model_request("谁是警察？", plain_settings)
    assert text_url == "https://example.test/v1/chat/completions" and not text_responses_api
    assert text_payload["messages"][0]["content"].startswith("推理学院问题：谁是警察？")
    local_sources = LOCAL_KNOWLEDGE.source_paths()
    assert len([path for path in local_sources if path.suffix.casefold() == ".pdf"]) == 23
    assert len([path for path in local_sources if path.suffix.casefold() == ".md"]) == 2
    field_questions = (
        ("第十二题：官方角色介绍中，菲璐的年龄是多少岁？", "22岁"),
        ("第十三题：官方角色介绍中，莫可是什么星座？", "双子座"),
    )
    for question, expected in field_questions:
        local_result = LOCAL_KNOWLEDGE.search(question)
        assert local_result.confident
        assert LOCAL_KNOWLEDGE.direct_answer(question, local_result.hits) == expected
    grounded_rule_questions = (
        ('第十题："谁是猪头王"游戏中，卡牌号码从1号到多少号？', "104"),
        ("第十五题：宝石矿工中，每隔多少秒会消除矿场最顶上的一整层？", "60秒"),
    )
    for question, expected in grounded_rule_questions:
        local_result = LOCAL_KNOWLEDGE.search(question)
        assert local_result.confident and answer_is_grounded(expected, local_result.hits)
        assert LOCAL_KNOWLEDGE.direct_answer(question, local_result.hits) is None
    pig_rule = LOCAL_KNOWLEDGE.search(grounded_rule_questions[0][0]).hits[0].text
    assert "当十张牌打完后" in pig_rule and "游戏中共有1-104号牌" in pig_rule
    animal_result = LOCAL_KNOWLEDGE.search('第八题："萌兽快跑"中，"万能牌"萌兽是？')
    assert animal_result.confident and answer_is_grounded("熊猫", animal_result.hits)
    relation_result = LOCAL_KNOWLEDGE.search(
        "第十一题：在《黑玫瑰》中，灰、库洛和阿布为之效力的‘老大’叫什么？"
    )
    assert relation_result.confident and answer_is_grounded("藤山", relation_result.hits)
    local_url, local_payload, local_responses_api = build_local_text_model_request(
        "老大叫什么？", relation_result, test_settings,
    )
    assert local_url == "https://example.test/v1/chat/completions" and not local_responses_api
    assert "藤山" in local_payload["messages"][0]["content"]
    assert not LOCAL_KNOWLEDGE.search("zzzznotinknowledgebase9999").confident
    assert DEFAULTS["dry_run_enabled"] is False
    assert DEFAULTS["google_search_enabled"] is True
    sample = 'RoomSay{"m":"问题：\\"谁是警察\\"？","u":[1,12345,"测试玩家","/a.png",0,[],2,false],"s":1}'
    assert parse_room_say(sample) == ("12345", "测试玩家", '问题："谁是警察"？')
    assert parse_room_say("SM{}") is None
    with tempfile.TemporaryDirectory() as directory:
        bot_config = Path(directory) / "config.json"
        bot_config.write_text(json.dumps({
            "login_token": "token", "login_device": "html5:test", "login_p": "p", "login_z": 1,
        }), encoding="utf-8")
        assert load_bot_login(str(bot_config)) == ("token", "html5:test", "p", 1)
    assert room_server_index_for_line(3) == 0
    assert room_server_index_for_line(2) == 1
    assert room_server_index_for_line(99) is None
    assert next_room_server_index(0) == 1
    assert next_room_server_index(0, 3) == 3
    room_client = RoomClient(queue.Queue())
    try:
        room_client.join({"bot_config_path": "config.json", "room": {"id": "3147", "password": "", "player": "佐"}})
    except RuntimeError as exc:
        assert "连接/登录" in str(exc)
    else:
        raise AssertionError("joining must require an established login")

    class AliveThread:
        @staticmethod
        def is_alive():
            return True

    room_client.thread = AliveThread()
    room_client.login_signature = "config.json"
    room_client.logged_in = True
    room_client.joined_room_id = "3147"
    changed_player = {"bot_config_path": "config.json", "room": {"id": "3147", "password": "new", "player": "另一人"}}
    assert room_client.login_active_for(changed_player)
    room_client.set_player(changed_player["room"]["player"])
    assert room_client.target_player == "另一人"
    print("self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        root = tk.Tk()
        QuizApp(root)
        root.mainloop()
