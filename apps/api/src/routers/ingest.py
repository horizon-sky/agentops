"""文档入库：解析 → 切分 → 向量化 → 落库（需要配置 DATABASE_URL）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.src.deps import require_token, settings_dep
from apps.api.src.schemas.api import IngestIn, IngestOut
from src.config import Settings

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_token)])


@router.post("", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
async def ingest_document_api(
    payload: IngestIn,
    settings: Settings = Depends(settings_dep),
) -> IngestOut:
    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置 DATABASE_URL，无法入库（RAG 依赖 Postgres + pgvector）",
        )

    from src.rag.ingest import ingest_document

    try:
        document_id, chunks, embedded = await ingest_document(
            title=payload.title,
            source=payload.source,
            content=payload.content,
            version=payload.version,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"入库失败：{str(exc)[:200]}",
        ) from exc

    return IngestOut(document_id=uuid.UUID(str(document_id)), chunks=chunks, embedded=embedded)
