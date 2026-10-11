"""Authenticated source-chunk preview, scoped to the document owner."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import Principal, auth_db, current_user, settings_dep
from apps.api.src.schemas.api import DocumentDetailOut, DocumentOut, DocumentUpdateIn
from src.config import Settings
from src.db.models import Chunk, Document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> list[DocumentOut]:
    rows = await db.execute(
        select(
            Document,
            func.count(Chunk.id).label("chunk_count"),
            func.count(Chunk.embedding).label("embedded_count"),
        )
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.owner_id == identity.user.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
    )
    return [
        DocumentOut(
            id=document.id,
            title=document.title,
            source=document.source,
            version=document.version,
            created_at=document.created_at,
            chunks=chunk_count,
            embedded=embedded_count,
        )
        for document, chunk_count, embedded_count in rows.all()
    ]


@router.get("/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> DocumentDetailOut:
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == identity.user.id)
    )
    if document is None:
        raise HTTPException(404, "文档不存在")
    chunks = list(
        await db.scalars(select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.seq))
    )
    embedded = sum(1 for chunk in chunks if chunk.embedding is not None)
    return DocumentDetailOut(
        id=document.id,
        title=document.title,
        source=document.source,
        version=document.version,
        created_at=document.created_at,
        chunks=len(chunks),
        embedded=embedded,
        content="\n\n".join(chunk.content for chunk in chunks),
    )


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: UUID,
    payload: DocumentUpdateIn,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
    identity: Principal = Depends(current_user),
) -> DocumentOut:
    if len(payload.content.encode("utf-8")) > 1_000_000:
        raise HTTPException(413, "单次文档上传不能超过 1 MB")
    from src.rag.ingest import update_document as rebuild_document

    try:
        updated_id, chunks, embedded = await rebuild_document(
            document_id=document_id,
            title=payload.title,
            source=payload.source,
            content=payload.content,
            version=payload.version,
            settings=settings,
            owner_id=identity.user.id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, "更新失败，请检查数据库与 Embedding 服务配置后重试") from exc

    db_document = await db.scalar(select(Document).where(Document.id == updated_id))
    if db_document is None:
        raise HTTPException(404, "文档不存在")
    return DocumentOut(
        id=db_document.id,
        title=db_document.title,
        source=db_document.source,
        version=db_document.version,
        created_at=db_document.created_at,
        chunks=chunks,
        embedded=embedded,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> None:
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == identity.user.id)
    )
    if document is None:
        raise HTTPException(404, "文档不存在")
    await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    await db.delete(document)
    await db.commit()


class ChunkOut(BaseModel):
    citation_id: UUID
    document_id: UUID
    title: str
    source_url: str
    heading: str
    content: str


@router.get("/{document_id}/chunks/{citation_id}", response_model=ChunkOut)
async def preview_chunk(
    document_id: UUID,
    citation_id: UUID,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> ChunkOut:
    row = (
        await db.execute(
            select(Chunk, Document)
            .join(Document)
            .where(
                Chunk.id == citation_id,
                Document.id == document_id,
                Document.owner_id == identity.user.id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(404, "原文片段不存在")
    chunk, document = row
    return ChunkOut(
        citation_id=chunk.id,
        document_id=document.id,
        title=document.title,
        source_url=document.source,
        heading=(chunk.meta or {}).get("heading", ""),
        content=chunk.content,
    )
