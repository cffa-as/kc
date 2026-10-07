#!/usr/bin/env python3
"""Monitor a player's online status and persist observed time ranges."""

from __future__ import annotations

import argparse
import json
import queue
import re
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
BOT_CONFIG_PATH = APP_DIR.parent / "websocket-bot" / "config.json"
NOTIFY_CONFIG_PATH = APP_DIR / "config.json"
HISTORY_PATH = APP_DIR / "online_history.json"
POLL_SECONDS = 60
MAX_CONTINUOUS_GAP_SECONDS = 150
API_URL = "https://t1.ss911.cn/User/MyF.ss"


class PlayerCountError(RuntimeError):
    """The API succeeded but did not return the requested player."""


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def remove_user_ids(history: dict) -> bool:
    changed = False
    for item in history.get("players", {}).values():
        if "user_id" in item:
            del item["user_id"]
            changed = True
    return changed


def player_from_payload(payload: dict) -> dict:
    data = payload.get("data")
    data = data if isinstance(data, list) else []
    try:
        count = int(payload.get("count", len(data)))
    except (TypeError, ValueError):
        count = len(data)
    if count < 1 or len(data) < 1:
        message = str(payload.get("msg") or "未知")
        raise PlayerCountError(f"玩家数据异常：count={count}，data={len(data)}条，msg={message}")
    if payload.get("msg") != "OK":
        raise RuntimeError(str(payload.get("msg") or "接口查询失败"))
    return data[0]


def fetch_player(sid: str) -> dict:
    config = load_json(BOT_CONFIG_PATH, {})
    encoded_u = str(config.get("u", "")).strip()
    if not encoded_u:
        raise RuntimeError(f"配置中缺少 u：{BOT_CONFIG_PATH}")
    query = urllib.parse.urlencode({
        "p": 1,
        "t": 5,
        "sid": sid,
        "u": urllib.parse.unquote(encoded_u),
    })
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return player_from_payload(payload)


def send_wecom_notification(content: str) -> None:
    webhook = str(load_json(NOTIFY_CONFIG_PATH, {}).get("wecom_webhook", "")).strip()
    if not webhook:
        raise RuntimeError(f"通知配置中缺少 wecom_webhook：{NOTIFY_CONFIG_PATH}")
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"msgtype": "text", "text": {"content": content}}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"企微请求失败：{exc.reason}") from exc
    if result.get("errcode") != 0:
        raise RuntimeError(f"企微返回错误：{result.get('errmsg') or result.get('errcode')}")


def record_observation(history: dict, sid: str, player: dict, checked_at: str) -> dict:
    players = history.setdefault("players", {})
    item = players.setdefault(sid, {"periods": []})
    is_online = int(player.get("online", 0)) == 1
    periods = item.setdefault("periods", [])
    previous_at = item.get("last_checked_at", "")
    continuous = False
    if previous_at:
        try:
            gap = (datetime.fromisoformat(checked_at) - datetime.fromisoformat(previous_at)).total_seconds()
            continuous = 0 <= gap <= MAX_CONTINUOUS_GAP_SECONDS
        except ValueError:
            pass
    if periods and periods[-1].get("online") == is_online and continuous:
        periods[-1]["end"] = checked_at
        periods[-1]["samples"] = int(periods[-1].get("samples", 1)) + 1
    else:
        periods.append({
            "online": is_online,
            "start": checked_at,
            "end": checked_at,
            "samples": 1,
        })
    item.update({
        "sid": sid,
        "user_name": str(player.get("userName", "")),
        "last_online_value": player.get("online", 0),
        "last_checked_at": checked_at,
    })
    item.pop("user_id", None)
    history["last_sid"] = sid
    return item


def online_notification_pending(item: dict) -> bool:
    periods = item.get("periods") or []
    return bool(
        periods
        and periods[-1].get("online")
        and item.get("notified_online_start") != periods[-1].get("start")
    )


def notify_online(sid: str, item: dict) -> None:
    period = item["periods"][-1]
    send_wecom_notification(
        "玩家上线提醒\n"
        f"{item.get('user_name') or sid} 已上线\n"
        f"SID：{sid}\n"
        f"时间：{display_time(period.get('start', ''))}"
    )
    item["notified_online_start"] = period.get("start")


def notify_query_problem(sid: str, error: Exception) -> None:
    send_wecom_notification(
        "玩家在线监控告警\n"
        f"SID：{sid}\n"
        f"问题：{error}\n"
        "可能是 u 参数失效或查询接口异常\n"
        f"时间：{display_time(now_text())}"
    )


def display_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value or "")


def display_duration(start: str, end: str) -> str:
    try:
        seconds = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except (TypeError, ValueError):
        return ""
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}时{minutes:02d}分" if hours else f"{minutes}分{seconds:02d}秒"


def parse_sids(value: str) -> list[str]:
    sids = list(dict.fromkeys(part for part in re.split(r"[,，;；\s]+", value.strip()) if part))
    if not sids or any(not sid.isdigit() for sid in sids):
        raise ValueError("SID 必须是数字，多个 SID 用逗号或空格分隔")
    return sids


class MonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("玩家在线监控")
        self.root.geometry("940x540")
        self.events: queue.Queue = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.running_sids: list[str] = []

        history = load_json(HISTORY_PATH, {})
        if remove_user_ids(history):
            save_json(HISTORY_PATH, history)
        saved_sids = history.get("last_sids") or [history.get("last_sid", "")]
        self.sids = tk.StringVar(value=", ".join(str(sid) for sid in saved_sids if sid))
        self.summary = tk.StringVar(value="输入一个或多个 SID 后开始监控")
        self.detail = tk.StringVar(value=f"每 {POLL_SECONDS} 秒查询一次")

        controls = ttk.Frame(root, padding=12)
        controls.pack(fill="x")
        ttk.Label(controls, text="SID（逗号或空格分隔）").pack(side="left")
        self.sid_entry = ttk.Entry(controls, textvariable=self.sids, width=38)
        self.sid_entry.pack(side="left", padx=(8, 10))
        self.start_button = ttk.Button(controls, text="开始监控", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.clear_button = ttk.Button(controls, text="清空历史", command=self.clear_history)
        self.clear_button.pack(side="left", padx=(8, 0))

        status = ttk.Frame(root, padding=(12, 4, 12, 10))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.summary, font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        ttk.Label(status, textvariable=self.detail).pack(anchor="w", pady=(4, 0))

        table_frame = ttk.Frame(root, padding=(12, 0, 12, 12))
        table_frame.pack(fill="both", expand=True)
        columns = ("player", "sid", "status", "start", "end", "duration")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.table.heading("player", text="玩家")
        self.table.heading("sid", text="SID")
        self.table.heading("status", text="状态")
        self.table.heading("start", text="开始")
        self.table.heading("end", text="最后确认")
        self.table.heading("duration", text="已观察时长")
        self.table.column("player", width=110, anchor="center")
        self.table.column("sid", width=110, anchor="center")
        self.table.column("status", width=70, anchor="center", stretch=False)
        self.table.column("start", width=170, anchor="center")
        self.table.column("end", width=170, anchor="center")
        self.table.column("duration", width=105, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.table.tag_configure("online", foreground="#08783e")
        self.table.tag_configure("offline", foreground="#b42318")

        if saved_sids and all(str(sid).isdigit() for sid in saved_sids):
            self.show_histories([str(sid) for sid in saved_sids])
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(200, self.pump_events)

    def show_histories(
        self, sids: list[str], history: dict | None = None,
        errors: list[str] | None = None, notices: list[str] | None = None,
    ) -> None:
        history = history or load_json(HISTORY_PATH, {})
        players = history.get("players", {})
        self.table.delete(*self.table.get_children())
        rows = []
        for sid in sids:
            item = players.get(sid, {})
            for period in item.get("periods", []):
                rows.append((period.get("start", ""), sid, item, period))
        for _, sid, item, period in sorted(rows, key=lambda row: row[0], reverse=True):
            online = bool(period.get("online"))
            self.table.insert("", "end", values=(
                item.get("user_name") or sid,
                sid,
                "在线" if online else "离线",
                display_time(period.get("start", "")),
                display_time(period.get("end", "")),
                display_duration(period.get("start", ""), period.get("end", "")),
            ), tags=("online" if online else "offline",))
        items = [players[sid] for sid in sids if sid in players]
        online_count = sum(int(item.get("last_online_value", 0)) == 1 for item in items)
        self.summary.set(f"已记录 {len(items)} 人：在线 {online_count}，离线 {len(items) - online_count}")
        last_checked = max((item.get("last_checked_at", "") for item in items), default="")
        detail = f"每 {POLL_SECONDS} 秒并发查询；最后查询 {display_time(last_checked)}"
        if notices:
            detail += "；已通知：" + "、".join(notices)
        if errors:
            detail += "；失败：" + "；".join(errors)
        self.detail.set(detail)

    def start(self) -> None:
        try:
            sids = parse_sids(self.sids.get())
        except ValueError as exc:
            messagebox.showerror("SID 无效", str(exc))
            return
        if self.worker and self.worker.is_alive():
            return
        self.running_sids = sids
        self.stop_event = threading.Event()
        self.sid_entry.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.clear_button.configure(state="disabled")
        self.summary.set("正在查询...")
        self.worker = threading.Thread(target=self.poll, args=(sids, self.stop_event), daemon=True)
        self.worker.start()

    def poll(self, sids: list[str], stop_event: threading.Event) -> None:
        active_query_alerts: set[str] = set()
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(sids)), thread_name_prefix="status") as executor:
                while not stop_event.is_set():
                    history = load_json(HISTORY_PATH, {})
                    remove_user_ids(history)
                    errors = []
                    notices = []
                    futures = {executor.submit(fetch_player, sid): sid for sid in sids}
                    for future in as_completed(futures):
                        sid = futures[future]
                        try:
                            player = future.result()
                        except Exception as exc:
                            errors.append(f"{sid} {exc}")
                            if sid not in active_query_alerts:
                                try:
                                    notify_query_problem(sid, exc)
                                    active_query_alerts.add(sid)
                                    notices.append(f"{sid} 查询异常")
                                except Exception as notify_exc:
                                    errors.append(f"{sid} 告警失败：{notify_exc}")
                        else:
                            active_query_alerts.discard(sid)
                            record_observation(history, sid, player, now_text())
                    for sid in sids:
                        item = history.get("players", {}).get(sid, {})
                        if online_notification_pending(item):
                            try:
                                notify_online(sid, item)
                                notices.append(item.get("user_name") or sid)
                            except Exception as exc:
                                errors.append(f"{sid} 通知失败：{exc}")
                    history["last_sid"] = sids[0]
                    history["last_sids"] = sids
                    save_json(HISTORY_PATH, history)
                    self.events.put(("results", sids, history, errors, notices))
                    if stop_event.wait(POLL_SECONDS):
                        break
        finally:
            self.events.put(("stopped",))

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        self.stop_button.configure(state="disabled")
        self.detail.set("正在停止...")

    def clear_history(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not messagebox.askyesno("清空历史", "确定清空所有玩家的在线、离线历史记录吗？"):
            return
        save_json(HISTORY_PATH, {"players": {}})
        self.table.delete(*self.table.get_children())
        self.summary.set("历史记录已清空")
        self.detail.set(f"每 {POLL_SECONDS} 秒查询一次")

    def pump_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "results":
                    _, sids, history, errors, notices = event
                    self.show_histories(sids, history, errors, notices)
                elif event[0] == "stopped":
                    self.running_sids = []
                    self.sid_entry.configure(state="normal")
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.clear_button.configure(state="normal")
                    self.detail.set("监控已停止，历史记录已保存")
        except queue.Empty:
            pass
        self.root.after(200, self.pump_events)

    def close(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        self.root.destroy()


def self_test() -> None:
    assert parse_sids("123, 456 123；789") == ["123", "456", "789"]
    try:
        parse_sids("123, abc")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid SID must fail")
    assert player_from_payload({"msg": "OK", "count": 1, "data": [{"online": 0}]}) == {"online": 0}
    try:
        player_from_payload({"msg": "OK", "count": 0, "data": []})
    except PlayerCountError as exc:
        assert "count=0" in str(exc)
    else:
        raise AssertionError("empty player response must alert")
    history: dict = {}
    offline = {"online": 0, "userName": "测试", "userId": 1}
    online = {"online": 1, "userName": "测试", "userId": 1}
    item = record_observation(history, "123", offline, "2026-10-07T10:00:00+08:00")
    assert "user_id" not in item
    item = record_observation(history, "123", offline, "2026-10-07T10:01:00+08:00")
    assert len(item["periods"]) == 1 and item["periods"][0]["samples"] == 2
    item = record_observation(history, "123", online, "2026-10-07T10:02:00+08:00")
    assert len(item["periods"]) == 2 and item["periods"][-1]["online"] is True
    assert online_notification_pending(item)
    item["notified_online_start"] = item["periods"][-1]["start"]
    assert not online_notification_pending(item)
    item = record_observation(history, "123", online, "2026-10-07T11:00:00+08:00")
    assert len(item["periods"]) == 3 and online_notification_pending(item)
    item["user_id"] = "legacy"
    assert remove_user_ids(history) and "user_id" not in item
    print("self-test ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    root = tk.Tk()
    MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
