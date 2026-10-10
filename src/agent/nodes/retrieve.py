"""知识检索：调用 M4 的混合检索（向量 + BM25 + RRF + Rerank）。

M4 未就绪或数据库不可用时降级为空结果，并在事件中如实标注，
避免「假装检索过」导致引用造假。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from apps.api.src.schemas.events import AgentEvent
from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder
from src.config import get_settings
from src.db.models import Chunk, Document
from src.db.session import get_session_factory


async def retrieve(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings") or get_settings()
    emit = get_emit(config)
    timer = Timer()
    plan = state.get("plan")
    selected = next((s for s in (plan or {}).get("steps", [])
                     if s["id"] in state.get("active_step_ids", [])), None)
    query = (selected or {}).get("args", {}).get("query", state["query"])

    citations: list[dict[str, Any]] = []
    diagnostic = {"mode": "graph", "status": "unavailable", "reason": "database_missing"}
    try:
        from src.rag.hybrid_search import hybrid_search

        owner_id = ctx_get("user_id")
        factory = get_session_factory(settings)
        if not owner_id:
            diagnostic["reason"] = "identity_missing"
        elif factory is not None:
            async with factory() as db:
                count = await db.scalar(
                    select(func.count())
                    .select_from(Chunk)
                    .join(Document)
                    .where(Document.owner_id == UUID(owner_id))
                )
            if not count:
                diagnostic.update(status="no_documents", reason="empty_library")
            else:
                hits = await hybrid_search(
                    query, top_k=5, settings=settings, owner_id=owner_id
                )
                citations = [hit.model_dump() for hit in hits]
                diagnostic.update(
                    status="hit" if citations else "no_match",
                    reason="matched" if citations else "no_match",
                )
    except Exception:  # noqa: BLE001 - 不在事件中暴露数据库连接串或服务凭据
        diagnostic.update(status="unavailable", reason="retrieval_error")
    note = diagnostic["reason"]
    merged = {str(c.get("citation_id") or c.get("chunk_id")): c
              for c in state.get("citations", []) + citations}
    citations = list(merged.values())
    if selected:
        selected["status"] = "failed" if diagnostic["status"] == "unavailable" else "done"

    await TraceRecorder(settings, state.get("run_id")).record(
        run_id=state.get("run_id", ""),
        stage="retrieve",
        name="hybrid_search",
        inputs={"query": state["query"][:500]},
        outputs={"hits": len(citations), "note": note, "retrieval": diagnostic},
        ms=timer.ms,
    )
    event: AgentEvent = event_of(
        type="retrieve",
        run_id=state.get("run_id", ""),
        stage="retrieve",
        payload={
            "hits": len(citations),
            "note": note,
            "citations": citations,
            "retrieval": diagnostic,
        },
        ms=timer.ms,
    )
    await emit(event)
    result = {"citations": citations, "retrieval": diagnostic}
    if plan:
        result.update(plan=plan, execution_ms=state.get("execution_ms", 0) + timer.ms)
    return result
