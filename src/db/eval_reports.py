"""Transactional publication and reading of completed evaluation summaries."""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import EvalRun, User
from src.eval_report import CompletedEvalReport


def require_identical(existing: EvalRun, report: CompletedEvalReport) -> None:
    # Some supported database drivers return naive UTC timestamps.
    started = existing.started_at.replace(tzinfo=UTC) if (
        existing.started_at.tzinfo is None
    ) else existing.started_at
    ended = existing.generated_at
    if ended is not None and ended.tzinfo is None:
        ended = ended.replace(tzinfo=UTC)
    if (
        existing.git_sha != report.git_sha or existing.prompt_version != report.prompt_version
        or existing.model_version != report.model_version
        or existing.metrics != report.metrics.model_dump(mode="json")
        or existing.source != report.source.model_dump(mode="json")
        or started != report.started_at or ended != report.generated_at
    ):
        raise ValueError("Report UUID already exists with different content")


async def publish_report(db: AsyncSession, report: CompletedEvalReport, email: str) -> bool:
    """Return False for an identical existing report; failures never commit a partial summary."""
    try:
        # Keep the verified publisher's role stable through the transaction.
        user = await db.scalar(select(User).where(User.email == email.lower()).with_for_update())
        if user is None or not user.is_active or user.verified_at is None or user.role != "admin":
            raise ValueError("Publication requires a verified, active administrator")
        existing = await db.get(EvalRun, report.id)
        metrics = report.metrics.model_dump(mode="json")
        source = report.source.model_dump(mode="json")
        if existing is not None:
            require_identical(existing, report)
            await db.rollback()
            return False
        db.add(EvalRun(
            id=report.id, git_sha=report.git_sha, prompt_version=report.prompt_version,
            model_version=report.model_version, metrics=metrics, source=source,
            started_at=report.started_at, generated_at=report.generated_at, report_path="",
        ))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            # Another administrator may have committed this UUID after our first read.
            existing = await db.get(EvalRun, report.id)
            if existing is None:
                raise
            require_identical(existing, report)
            await db.rollback()
            return False
        return True
    except Exception:
        await db.rollback()
        raise


async def latest_report(db: AsyncSession) -> EvalRun | None:
    return await db.scalar(
        select(EvalRun).where(EvalRun.generated_at.is_not(None))
        .order_by(EvalRun.generated_at.desc(), EvalRun.id.desc()).limit(1)
    )
