#!/usr/bin/env python3
"""Ask Gemini with native Google Search grounding.

Usage:
    GEMINI_API_KEY=... python3 test_gemini_google_search.py

For an OpenAI-compatible proxy:
    GEMINI_BASE_URL=https://api.qnaigc.com/v1 GEMINI_MODEL=gemini-3.7-flash GEMINI_API_KEY=... python3 test_gemini_google_search.py
"""

from __future__ import annotations

import json
import os
import sys

import requests


QUESTION = "推理学院官方小说·《库洛：午夜的月光》，小师妹用彩纸折的是什么动物？"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")


def extract_answer(body: dict) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: list[str] = []
    for step in body.get("steps", []):
        if step.get("type") != "model_output":
            continue
        for content in step.get("content", []):
            if content.get("type") == "text" and content.get("text"):
                texts.append(str(content["text"]).strip())
    if texts:
        return texts[-1]
    raise RuntimeError("Gemini 返回中没有找到文本答案：" + json.dumps(body, ensure_ascii=False)[:1200])


def extract_chat_answer(body: dict) -> str:
    try:
        answer = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("代理返回中没有聊天答案：" + json.dumps(body, ensure_ascii=False)[:1200]) from exc
    answer = " ".join(str(answer or "").split()).strip()
    if not answer:
        raise RuntimeError("代理返回空答案：" + json.dumps(body, ensure_ascii=False)[:1200])
    return answer


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("缺少 GEMINI_API_KEY。请先执行：export GEMINI_API_KEY='你的 Google AI Studio Key'", file=sys.stderr)
        return 2

    prompt = (
        f"{QUESTION}\n\n"
        "请使用 Google Search 查证。只输出最终答案，不要解释，不要输出搜索过程或引用。"
    )
    is_google_native = "generativelanguage.googleapis.com" in BASE_URL and not BASE_URL.endswith("/openai")
    if is_google_native:
        url = BASE_URL + "/interactions"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        payload = {"model": MODEL, "input": prompt, "tools": [{"type": "google_search"}]}
    else:
        url = BASE_URL + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": MODEL,
            "temperature": 0,
            "max_tokens": 512,
            "enable_thinking": False,
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "messages": [{"role": "user", "content": prompt}],
        }
    response = requests.post(url, headers=headers, json=payload, timeout=(5, 60))
    if not response.ok:
        print(f"Gemini API {response.status_code}: {response.text[:2000]}", file=sys.stderr)
        return 1

    body = response.json()
    print(extract_answer(body) if is_google_native else extract_chat_answer(body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
