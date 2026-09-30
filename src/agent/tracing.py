"""Trace 落库：span 树写入 traces 表，供失败定位与前端回放。

无数据库时静默降级（仅打日志），不影响主链路。
"""

from __future__ import annotations

import logging
import uuid
from time import perf_counter
from typing import Any

from src.config import Settings
from src.db.models import Trace
from src.db.session import get_session_factory

logger = logging.getLogger("agentops.trace")


class TraceRecorder:
    def __init__(self, settings: Settings, run_id: str | None = None) -> None:
        self.settings = settings
        self.run_id = run_id

    async def record(
        self,
        *,
        run_id: str,
        stage: str,
        name: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        ms: int = 0,
        tokens: int = 0,
        cost: float = 0.0,
        status: str = "ok",
        parent_id: uuid.UUID | None = None,
    ) -> None:
        if not self.settings.has_database:
            return
        factory = get_session_factory(self.settings)
        if factory is None:
            return
        try:
            async with factory() as session:  # type: AsyncSession
                session.add(
                    Trace(
                        run_id=uuid.UUID(run_id),
                        parent_id=parent_id,
                        stage=stage,
                        name=name,
                        status=status,
                        ms=ms,
                        tokens=tokens,
                        cost=cost,
                        inputs=inputs or {},
                        outputs=outputs or {},
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - trace 失败不得影响主流程
            logger.exception("trace 写入失败 run_id=%s stage=%s", run_id, stage)


class Timer:
    """轻量计时器：用于节点耗时统计。"""

    def __init__(self) -> None:
        self._start = perf_counter()

    @property
    def ms(self) -> int:
        return int((perf_counter() - self._start) * 1000)
