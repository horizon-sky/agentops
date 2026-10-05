"""文档入库：解析 → 切分 → 向量化 → 落库 → 生成 BM25 用的 tsvector。"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from src.config import Settings
from src.db.models import Document
from src.db.session import get_session_factory
from src.rag.chunk import chunk_text
from src.rag.embed import embed_texts
from src.rag.parse import parse_text

INSERT_CHUNK_SQL = """
INSERT INTO chunks (id, document_id, chunk_id, seq, content, token_count, embedding, meta)
VALUES (
    gen_random_uuid(),
    CAST(:document_id AS uuid),
    :chunk_id,
    :seq,
    :content,
    :token_count,
    CAST(:embedding AS vector),
    CAST(:meta AS jsonb)
)
"""

UPDATE_TSV_SQL = """
UPDATE chunks
SET tsv = to_tsvector('simple', content)
WHERE document_id = CAST(:document_id AS uuid)
"""


def _vector_literal(vector: list[float]) -> str | None:
    if not vector:
        return None
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


async def ingest_document(
    *,
    title: str,
    source: str,
    content: str,
    version: str,
    settings: Settings,
    owner_id: uuid.UUID,
) -> tuple[uuid.UUID, int, int]:
    """返回 (document_id, 切分数量, 向量化数量)。"""
    factory = get_session_factory(settings)
    if factory is None:
        raise RuntimeError("未配置 DATABASE_URL，无法入库")

    clean_text = parse_text(content)
    chunks = chunk_text(clean_text)
    if not chunks:
        raise ValueError("文档内容为空或解析后无有效文本")

    vectors = await embed_texts([str(chunk["content"]) for chunk in chunks], settings)
    embedded = sum(1 for vector in vectors if vector)

    async with factory() as session:
        document = Document(title=title, source=source, version=version, owner_id=owner_id)
        session.add(document)
        await session.flush()

        for chunk, vector in zip(chunks, vectors, strict=False):
            await session.execute(
                text(INSERT_CHUNK_SQL),
                {
                    "document_id": str(document.id),
                    "chunk_id": chunk["chunk_id"],
                    "seq": chunk["seq"],
                    "content": chunk["content"],
                    "token_count": chunk["token_count"],
                    "embedding": _vector_literal(vector),
                    "meta": json.dumps(
                        {"heading": chunk["heading"], "version": version}, ensure_ascii=False
                    ),
                },
            )
        await session.execute(text(UPDATE_TSV_SQL), {"document_id": str(document.id)})
        await session.commit()
        return document.id, len(chunks), embedded
