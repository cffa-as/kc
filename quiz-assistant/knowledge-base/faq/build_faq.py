#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://faq.ss911.cn/faq/SysFaq_j.ss"
OUTPUT = Path(__file__).with_name("ss911-faq.md")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def fetch(**params):
    request = Request(f"{BASE_URL}?{urlencode(params)}", headers={"User-Agent": "kc-suite-faq-builder/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def plain_text(value):
    parser = TextExtractor()
    parser.feed(unescape(value or ""))
    text = "".join(parser.parts).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_answer(item):
    answer = plain_text(fetch(id=item["id"]).get("answer"))
    if not answer:
        raise RuntimeError(f"FAQ {item['id']} 没有返回答案：{item['title']}")
    return item["id"], answer


def main():
    items = fetch(p=1, ps=1000).get("list") or []
    if not items:
        raise RuntimeError("FAQ 目录接口没有返回内容")

    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise RuntimeError("FAQ 目录包含重复 ID")

    with ThreadPoolExecutor(max_workers=12) as pool:
        answers = dict(pool.map(load_answer, items))

    lines = [
        "# 推理学院官方常见问题整理",
        "",
        "本文档根据推理学院官方 FAQ 接口整理，适合直接上传到答题助手知识库。",
        f"整理日期：{date.today().isoformat()}；共 {len(items)} 条。FAQ ID 不连续，以官方目录接口返回内容为准。",
        "",
        f"目录来源：{BASE_URL}?p=1&ps=1000",
        "",
    ]

    for index, item in enumerate(items, 1):
        faq_id = item["id"]
        title = plain_text(item.get("title")).replace("\n", " ")
        lines.extend([
            f"## {index}. {title}",
            "",
            f"- FAQ ID：{faq_id}",
            f"- 官方来源：{BASE_URL}?id={faq_id}",
            "",
            "### 答案",
            "",
            answers[faq_id],
            "",
        ])

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {OUTPUT}：{len(items)} 条 FAQ")


if __name__ == "__main__":
    main()
