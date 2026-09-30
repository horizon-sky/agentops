"""知识检索：调用 M4 的混合检索（向量 + BM25 + RRF + Rerank）。

M4 未就绪或数据库不可用时降级为空结果，并在事件中如实标注，
避免「假装检索过」导致引用造假。
"""

from __future__ import annotations

from typing import Any

from apps.api.src.schemas.events import AgentEvent
from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder


async def retrieve(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    emit = get_emit(config)
    timer = Timer()

    citations: list[dict[str, Any]] = []
    note = "ok"
    try:
        from src.rag.hybrid_search import hybrid_search

        hits = await hybrid_search(state["query"], top_k=5, settings=settings)
        citations = [hit.model_dump() for hit in hits]
        if not citations:
            note = "empty"
    except Exception as exc:  # noqa: BLE001 - 检索失败不应中断链路
        note = f"unavailable: {str(exc)[:120]}"

    await TraceRecorder(settings, state.get("run_id")).record(
        run_id=state.get("run_id", ""),
        stage="retrieve",
        name="hybrid_search",
        inputs={"query": state["query"][:500]},
        outputs={"hits": len(citations), "note": note},
        ms=timer.ms,
    )
    event: AgentEvent = event_of(
        type="retrieve",
        run_id=state.get("run_id", ""),
        stage="retrieve",
        payload={"hits": len(citations), "note": note, "citations": citations},
        ms=timer.ms,
    )
    await emit(event)
    return {"citations": citations}
