"""Validated, public evaluation summaries; case inputs and outputs are never published."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Count = Annotated[int, Field(strict=True, ge=0)]
Measurement = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Percentage = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
Version = Annotated[str, Field(min_length=1, max_length=64)]


class EvalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: Annotated[int, Field(strict=True, gt=0)]
    citation_skipped: Count
    task_success_rate: Percentage
    tool_accuracy: Percentage
    recall_at_5: Percentage | None
    p50_latency_ms: Measurement
    p95_latency_ms: Measurement
    avg_tokens: Measurement | None
    cost_per_task: Measurement | None
    failure_stages: dict[str, Count]

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        if self.citation_skipped > self.cases or sum(self.failure_stages.values()) > self.cases:
            raise ValueError("Evaluation counts exceed the selected cases")
        if self.p95_latency_ms < self.p50_latency_ms:
            raise ValueError("P95 latency cannot be below P50")
        return self


class EvalFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["graph"]
    routing: bool
    retry: bool
    dynamic: bool


class EvalSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    environment: Literal["local", "staging", "ci"]
    golden_set_version: Version
    code_dirty: bool
    cheap_model: Version
    llm_configured: bool
    database_configured: bool
    embedding_configured: bool
    rerank_configured: bool
    configured_retrieval_mode: Literal["hybrid", "bm25", "unavailable"]
    tool_data_source: Literal["sample"]
    agent_flags: EvalFlags


class CompletedEvalReport(BaseModel):
    # Local reports may carry private `results`; only these whitelisted fields survive.
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[1]
    id: UUID
    status: Literal["completed"]
    started_at: AwareDatetime
    generated_at: AwareDatetime
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    prompt_version: Version
    model_version: Version
    selected_cases: Annotated[int, Field(strict=True, gt=0)]
    source: EvalSource
    metrics: EvalMetrics

    @model_validator(mode="after")
    def check_completed(self) -> Self:
        if self.generated_at < self.started_at:
            raise ValueError("Report completion precedes its start")
        if self.metrics.cases != self.selected_cases:
            raise ValueError("Not all selected evaluation cases completed")
        return self
