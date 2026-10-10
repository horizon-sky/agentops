"""Validated execution plans; policy and risk remain server-owned."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.agent.nodes.tools import _planned_calls


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["retrieve", "tool", "answer"]
    goal: str = Field(min_length=1, max_length=500)
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    status: Literal["pending", "running", "done", "failed", "denied", "skipped"] = "pending"


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    steps: list[PlanStep] = Field(default_factory=list, max_length=8)


class RetrievalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)


def static_plan(state: dict[str, Any]) -> ExecutionPlan:
    intent, query = state.get("intent", "general"), state["query"]
    routing = state.get("flags", {}).get("routing", False)
    retrieve = not routing or intent in {"incident", "knowledge", "ticket"}
    calls = state.get("pending_calls")
    if calls is None:
        calls = _planned_calls(state) if (not routing or intent != "general") else []
    steps: list[PlanStep] = []
    if intent == "injection":
        calls, retrieve = [], False
    if retrieve:
        steps.append(
            PlanStep(id="retrieve", kind="retrieve", goal="检索个人知识库", args={"query": query})
        )
    read_ids: list[str] = []
    for index, call in enumerate(calls):
        write = call["name"] in {"create_ticket", "draft_report"}
        deps = (["retrieve"] if retrieve else []) + (read_ids if write else [])
        steps.append(
            PlanStep(
                id=f"tool-{index}",
                kind="tool",
                goal=call["name"],
                tool=call["name"],
                args=call.get("args", {}),
                depends_on=deps,
            )
        )
        if not write:
            read_ids.append(f"tool-{index}")
    if (
        intent != "injection"
        and re.search(
            r"(?:生成|撰写|编写|起草|输出|写|制作|整理).{0,12}报告"
            r"|\b(?:draft|create|generate|write|produce)\b.{0,40}\breport\b",
            query,
            re.IGNORECASE,
        )
        and not any(s.tool == "draft_report" for s in steps)
    ):
        steps.append(
            PlanStep(
                id="report",
                kind="tool",
                goal="生成处理报告",
                tool="draft_report",
                args={"title": query[:300]},
                depends_on=[s.id for s in steps],
            )
        )
    steps.append(
        PlanStep(
            id="answer", kind="answer", goal="基于现有证据回答", depends_on=[s.id for s in steps]
        )
    )
    return ExecutionPlan(steps=steps)


def validate_plan(plan: ExecutionPlan, state: dict[str, Any], registry: Any) -> ExecutionPlan:
    ids = [step.id for step in plan.steps]
    if len(ids) != len(set(ids)) or not ids or len(ids) > 8:
        raise ValueError("Invalid step IDs or plan size")
    expected = static_plan({**state, "flags": {"routing": True}})
    allowed = {s.tool for s in expected.steps if s.tool}
    for step in plan.steps:
        if not set(step.depends_on).issubset(ids):
            raise ValueError("Unknown dependency")
        step.status = "pending"
        if step.kind == "tool":
            if step.tool not in allowed or step.tool not in registry.specs:
                raise ValueError("Tool outside intent policy")
            spec = registry.specs[step.tool]
            step.args = spec.args_model.model_validate(step.args).model_dump(exclude_none=True)
            if registry.is_high_risk(step.tool):
                step.args.pop("idempotency_key", None)
        elif step.tool is not None:
            raise ValueError("Non-tool step has tool")
        elif step.kind == "retrieve":
            step.args = RetrievalArgs.model_validate(step.args).model_dump()
        elif step.args:
            raise ValueError("Answer step cannot carry tool arguments")
    deps = {s.id: set(s.depends_on) for s in plan.steps}
    visited: set[str] = set()
    while len(visited) < len(deps):
        roots = {key for key, values in deps.items() if key not in visited and values <= visited}
        if not roots:
            raise ValueError("Cyclic plan")
        visited.update(roots)

    def ancestors(step_id: str) -> set[str]:
        result = set(deps[step_id])
        for dependency in deps[step_id]:
            result.update(ancestors(dependency))
        return result

    if len([s for s in plan.steps if s.kind == "answer"]) != 1:
        raise ValueError("Plan requires one answer")
    answer = next(s for s in plan.steps if s.kind == "answer")
    if ancestors(answer.id) != set(ids) - {answer.id}:
        raise ValueError("Answer must depend on all evidence")
    required = {s.tool for s in expected.steps if s.tool}
    if not required.issubset({s.tool for s in plan.steps}):
        raise ValueError("Missing required tools")
    retrievals = {s.id for s in plan.steps if s.kind == "retrieve"}
    if any(s.kind == "retrieve" for s in expected.steps) and not retrievals:
        raise ValueError("Missing required retrieval")
    for step in plan.steps:
        if step.tool and registry.is_high_risk(step.tool):
            reads = {
                s.id for s in plan.steps if s.kind == "tool" and not registry.is_high_risk(s.tool)
            }
            if not (reads | retrievals) <= ancestors(step.id):
                raise ValueError("Writes must follow evidence collection")
    return plan
