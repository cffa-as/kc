"""Fast local text retrieval for the quiz knowledge files."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import threading
import time
import unicodedata


INDEX_VERSION = 2
QUESTION_PREFIX = re.compile(r"^\s*第[0-9一二三四五六七八九十百零两]+题\s*[：:、.]?\s*")


@dataclass(frozen=True)
class SearchHit:
    source: str
    locator: str
    text: str
    snippet: str
    score: float


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    elapsed_ms: float
    coverage: float
    confident: bool


def clean_question(question: str) -> str:
    text = unicodedata.normalize("NFKC", question).strip()
    text = QUESTION_PREFIX.sub("", text)
    for phrase in ("根据官方角色介绍", "官方角色介绍中", "官方角色介绍里", "请问"):
        text = text.replace(phrase, "")
    return (
        text.replace("多少岁", "年龄")
        .replace("是什么星座", "星座")
        .replace("什么星座", "星座")
        .replace("叫什么名字", "名字")
        .replace("叫什么", "名字")
    )


def _normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in unicodedata.normalize("NFKC", text).splitlines()]
    return "\n".join(line for line in lines if line)


def _features(text: str) -> Counter[str]:
    features: Counter[str] = Counter()
    for token in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", text.casefold()):
        if re.fullmatch(r"[a-z0-9]+", token):
            features[token] += 1
            continue
        if len(token) == 1:
            features[token] += 1
        for size in (2, 3):
            features.update(token[index:index + size] for index in range(len(token) - size + 1))
    return features


def _query_text(question: str) -> str:
    text = clean_question(question)
    for field in ("年龄", "星座", "生日", "身高", "体重"):
        text = text.replace(field, f" {field} ")
    for phrase in (
        "推理学院", "官方", "小说", "问题", "有哪些角色", "有哪些",
        "什么", "名字", "哪一个", "哪个",
    ):
        text = text.replace(phrase, " ")
    for character in "的是在中和与及为之":
        text = text.replace(character, " ")
    aliases = []
    if "老大" in text:
        aliases.extend(("教父", "头子", "首领"))
    return " ".join((text, *aliases))


def _field_entity(question: str, field: str) -> str:
    patterns = (
        rf"([\u3400-\u9fffA-Za-z0-9·]{{1,10}}?)的{field}",
        rf"([\u3400-\u9fffA-Za-z0-9·]{{1,10}}?)(?:是)?什么{field}",
    )
    return next(
        (match.group(1) for pattern in patterns if (match := re.search(pattern, question))),
        "",
    )


def _query_anchors(question: str) -> set[str]:
    text = clean_question(question)
    anchors = set(re.findall(r"[《\"“]([^》\"”]{2,24})[》\"”]", text))
    anchors.update(
        match.group(1)
        for match in re.finditer(r"([\u3400-\u9fffA-Za-z0-9·]{2,20})(?:游戏)?中", text)
    )
    return anchors


def _markdown_chunks(path: Path) -> list[dict]:
    chunks: list[dict] = []
    headings: dict[int, str] = {}
    body: list[str] = []

    def flush() -> None:
        text = _normalize_text("\n".join((*[headings[level] for level in sorted(headings)], *body)))
        if text:
            chunks.append({"source": str(path), "locator": " / ".join(headings.values()), "text": text})

    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if not match:
            body.append(line)
            continue
        level = len(match.group(1))
        if level > 2:
            body.append(line)
            continue
        flush()
        headings[level] = match.group(2)
        headings = {key: value for key, value in headings.items() if key <= level}
        body = []
    flush()
    return chunks


class LocalKnowledge:
    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.cache_path = app_dir / "tmp" / "local_knowledge_index.json"
        self._lock = threading.Lock()
        self._chunks: list[dict] = []
        self._counters: list[Counter[str]] = []
        self._prefix_features: list[set[str]] = []
        self._document_frequency: Counter[str] = Counter()
        self._average_length = 1.0
        self._loaded = False

    def source_paths(self) -> list[Path]:
        pdfs = sorted((self.app_dir / "output" / "pdf").rglob("*.pdf"))
        markdown = [
            self.app_dir / "knowledge-base" / "game-help" / "ss911-game-help.md",
            self.app_dir / "knowledge-base" / "faq" / "ss911-faq.md",
        ]
        return pdfs + [path for path in markdown if path.exists()]

    def _signature(self, paths: list[Path]) -> list[dict]:
        return [
            {
                "path": str(path.relative_to(self.app_dir)),
                "size": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in paths
        ]

    def ensure_loaded(self) -> int:
        with self._lock:
            if self._loaded:
                return len(self._chunks)
            paths = self.source_paths()
            signature = self._signature(paths)
            chunks = None
            try:
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if cached.get("version") == INDEX_VERSION and cached.get("sources") == signature:
                    chunks = cached.get("chunks")
            except (OSError, ValueError, AttributeError):
                pass
            if not isinstance(chunks, list):
                chunks = self._build(paths)
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.cache_path.with_suffix(".tmp")
                temporary.write_text(json.dumps({
                    "version": INDEX_VERSION, "sources": signature, "chunks": chunks,
                }, ensure_ascii=False), encoding="utf-8")
                temporary.replace(self.cache_path)
            self._prepare(chunks)
            self._loaded = True
            return len(self._chunks)

    def _build(self, paths: list[Path]) -> list[dict]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("本地知识库需要 pypdf，请先执行 pip install -r requirements.txt") from exc

        chunks: list[dict] = []
        for path in paths:
            if path.suffix.casefold() == ".md":
                chunks.extend(_markdown_chunks(path))
                continue
            reader = PdfReader(path)
            for page_number, page in enumerate(reader.pages, 1):
                text = _normalize_text(page.extract_text() or "")
                if text:
                    chunks.append({"source": str(path), "locator": f"第 {page_number} 页", "text": text})
        return chunks

    def _prepare(self, chunks: list[dict]) -> None:
        self._chunks = chunks
        self._counters = [_features(chunk["text"]) for chunk in chunks]
        self._prefix_features = [set(_features(chunk["text"][:240])) for chunk in chunks]
        self._document_frequency = Counter(
            feature for counter in self._counters for feature in counter
        )
        self._average_length = (
            sum(sum(counter.values()) for counter in self._counters) / max(1, len(self._counters))
        )

    def search(self, question: str, limit: int = 5) -> SearchResult:
        started = time.perf_counter()
        self.ensure_loaded()
        query = _features(_query_text(question))
        if not query or not self._chunks:
            return SearchResult((), (time.perf_counter() - started) * 1000, 0.0, False)

        total_documents = len(self._chunks)
        weights = {
            feature: math.log(1 + (total_documents - self._document_frequency[feature] + 0.5)
                              / (self._document_frequency[feature] + 0.5))
            for feature in query
        }
        scores: list[tuple[float, int]] = []
        field = next((name for name in ("年龄", "星座", "生日", "身高", "体重") if name in clean_question(question)), "")
        entity = _field_entity(question, field) if field else ""
        for index, counter in enumerate(self._counters):
            document_length = sum(counter.values())
            score = 0.0
            for feature, query_count in query.items():
                frequency = counter.get(feature, 0)
                if not frequency:
                    continue
                denominator = frequency + 1.2 * (0.25 + 0.75 * document_length / self._average_length)
                score += weights[feature] * frequency * 2.2 / denominator * (1 + math.log(query_count))
                if feature in self._prefix_features[index]:
                    score += weights[feature] * 4.0
            if entity and entity in self._chunks[index]["text"][:100]:
                score += 30.0
            if score:
                scores.append((score, index))
        scores.sort(reverse=True)

        selected = scores[:limit]
        matched = {
            feature for _score, index in selected for feature in query if feature in self._counters[index]
        }
        total_weight = sum(weights[feature] * count for feature, count in query.items()) or 1.0
        coverage = sum(weights[feature] * query[feature] for feature in matched) / total_weight
        hits = tuple(self._make_hit(index, score, query, weights) for score, index in selected)
        top_score = selected[0][0] if selected else 0.0
        anchors = _query_anchors(question)
        anchored = any(
            anchor in self._chunks[index]["locator"] or anchor in self._chunks[index]["text"][:160]
            for _score, index in selected
            for anchor in anchors
        )
        confident = bool(hits and top_score >= 5.0 and (coverage >= 0.45 or anchored))
        return SearchResult(hits, (time.perf_counter() - started) * 1000, coverage, confident)

    def _make_hit(
        self, index: int, score: float, query: Counter[str], weights: dict[str, float],
    ) -> SearchHit:
        chunk = self._chunks[index]
        text = chunk["text"]
        best_features = sorted(
            (feature for feature in query if feature in text.casefold()),
            key=lambda feature: (weights[feature], len(feature)),
            reverse=True,
        )
        positions = [text.casefold().find(feature) for feature in best_features[:5]]
        positions = [position for position in positions if position >= 0]
        start = max(0, (min(positions) if positions else 0) - 160)
        snippet = text[start:start + 1000]
        if start:
            snippet = "..." + snippet
        if start + 1000 < len(text):
            snippet += "..."
        source = str(Path(chunk["source"]).relative_to(self.app_dir))
        return SearchHit(source, chunk["locator"], text, snippet, score)

    @staticmethod
    def direct_answer(question: str, hits: tuple[SearchHit, ...]) -> str | None:
        fields = {
            "年龄": (r"年龄\s*[：:]\s*(\d+)\s*岁?", lambda value: value + "岁"),
            "星座": (r"星座\s*[：:]\s*([^\s，,。；;]+座)", str),
            "生日": (r"生日\s*[：:]\s*([^\s，,。；;]+)", str),
            "身高": (r"身高\s*[：:]\s*([\d.]+\s*(?:公分|厘米|cm)?)", str),
            "体重": (r"体重\s*[：:]\s*([\d.]+\s*(?:公斤|kg)?)", str),
        }
        field = next((name for name in fields if name in clean_question(question)), None)
        if not field:
            return None
        entity = _field_entity(question, field)
        pattern, formatter = fields[field]
        for hit in hits:
            if entity and entity not in hit.text[:100]:
                continue
            match = re.search(pattern, hit.text, re.IGNORECASE)
            if match:
                return formatter(match.group(1).strip())
        return None


def answer_is_grounded(answer: str, hits: tuple[SearchHit, ...]) -> bool:
    compact_answer = re.sub(r"[^\w\u3400-\u9fff]+", "", answer).casefold()
    compact_answer = re.sub(r"^(?:答案是|答案|答)", "", compact_answer)
    context = re.sub(r"[^\w\u3400-\u9fff]+", "", " ".join(hit.text for hit in hits)).casefold()
    if not compact_answer:
        return False
    return compact_answer in context or (
        compact_answer.endswith(("岁", "个")) and compact_answer[:-1] in context
    )
