"""切分：优先按 Markdown 标题切分，再对过长段落递归切分并保留重叠。"""

from __future__ import annotations

import hashlib
import re

DEFAULT_SIZE = 500
DEFAULT_OVERLAP = 80

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def split_by_headings(text: str) -> list[tuple[str, str]]:
    """返回 [(标题路径, 正文)]；无标题时整篇作为一段。"""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((match.group(2).strip(), body))
    return sections or [("", text)]


def recursive_split(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        pieces.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def chunk_text(
    text: str,
    size: int = DEFAULT_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, object]]:
    """返回 [{chunk_id, seq, heading, content, token_count}]。"""
    chunks: list[dict[str, object]] = []
    seq = 0
    for heading, body in split_by_headings(text):
        for piece in recursive_split(body, size, overlap):
            content = f"{heading}\n{piece}".strip() if heading else piece.strip()
            if not content:
                continue
            chunks.append(
                {
                    "chunk_id": _hash(content),
                    "seq": seq,
                    "heading": heading,
                    "content": content,
                    "token_count": max(1, len(content) // 3),  # 粗估，避免引入额外分词依赖
                }
            )
            seq += 1
    return chunks
