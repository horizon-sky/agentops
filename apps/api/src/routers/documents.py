"""Authenticated source-chunk preview, scoped to the document owner."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import Principal, auth_db, current_user
from src.db.models import Chunk, Document

router = APIRouter(prefix="/documents", tags=["documents"])


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
