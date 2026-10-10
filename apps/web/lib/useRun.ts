"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { abortRun, createRun, resumeRun, streamRun } from "./api";
import { isHitl, isToolResult } from "./api";
import type { AgentEvent, Citation, ExecutionPlan, HitlPayload, PlanStep, RetrievalDiagnostic, RunSnapshot, Stage, ToolResultPayload } from "./types";
import { retrievalMessage } from "./citations";

export interface TimelineStep {
  stage: Stage;
  label: string;
  status: "pending" | "running" | "done" | "error" | "skipped";
  ms: number;
  detail: string;
}

const STAGE_LABEL: Record<Stage, string> = {
  plan: "规划",
  retrieve: "检索",
  tools: "工具",
  generate: "生成",
};

function initialSteps(): TimelineStep[] {
  return (["plan", "retrieve", "tools", "generate"] as Stage[]).map((stage) => ({
    stage,
    label: STAGE_LABEL[stage],
    status: "pending",
    ms: 0,
    detail: "等待执行",
  }));
}

function evidenceStages(steps: TimelineStep[], plan: ExecutionPlan, retrieval?: RetrievalDiagnostic): TimelineStep[] {
  return steps.map(step => {
    if (step.stage !== "tools" && step.stage !== "retrieve") return step;
    const planned = plan.steps.filter(item => item.kind === (step.stage === "tools" ? "tool" : "retrieve"));
    if (!planned.length || planned.every(item => item.status === "skipped")) {
      return { ...step, status: "skipped", detail: "已跳过" };
    }
    if (planned.some(item => item.status === "running")) {
      return { ...step, status: "running", detail: "执行中" };
    }
    if (planned.some(item => item.status === "pending")) {
      return { ...step, status: "pending", detail: "等待执行" };
    }
    const failed = planned.some(item => item.status === "failed" || item.status === "denied");
    if (step.stage === "retrieve") {
      return { ...step, status: failed ? "error" : "done", detail: retrieval
        ? retrievalMessage(retrieval) : step.detail };
    }
    return { ...step, status: failed ? "error" : "done", detail: failed ? "部分操作未完成" : "已完成" };
  });
}

export function useRun() {
  const [runId, setRunId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [steps, setSteps] = useState<TimelineStep[]>(initialSteps);
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [retrieval, setRetrieval] = useState<RetrievalDiagnostic | null>(null);
  const [tools, setTools] = useState<ToolResultPayload[]>([]);
  const [hitl, setHitl] = useState<HitlPayload | null>(null);
  const [status, setStatus] = useState<"idle" | "running" | "waiting" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const seenEvents = useRef(new Set<string>());

  useEffect(() => () => controllerRef.current?.abort(), []);

  const reportError = useCallback((reason: unknown) => {
    setStatus("error");
    setError(reason instanceof Error ? reason.message : "请求失败，请重试");
  }, []);

  const patchStep = useCallback((stage: Stage, patch: Partial<TimelineStep>) => {
    setSteps((prev) =>
      prev.map((step) => (step.stage === stage ? { ...step, ...patch } : step)),
    );
  }, []);

  const handleEvent = useCallback(
    (event: AgentEvent) => {
      if (seenEvents.current.has(event.id)) return;
      seenEvents.current.add(event.id);
      const payload = event.payload ?? {};
      const stage = event.stage ?? "plan";

      switch (event.type) {
        case "plan":
          if (payload.status === "skipped") {
            patchStep(stage, { status: "skipped", detail: "本次无需执行" });
          } else if (payload.plan && Array.isArray((payload.plan as ExecutionPlan).steps)) {
            const planned = (payload.plan as ExecutionPlan).steps;
            setPlan(planned);
            setSteps(prev => evidenceStages(prev, payload.plan as ExecutionPlan));
            patchStep("plan", { status: "done", ms: event.ms ?? 0, detail: planned.map(s => s.goal).join(" → ") });
          } else if (!payload.review) {
            patchStep("plan", { status: "running", detail: "正在分析问题并制定计划" });
          }
          break;
        case "retrieve":
          setRetrieval((payload.retrieval as RetrievalDiagnostic) ?? null);
          patchStep("retrieve", {
            status: (payload.retrieval as RetrievalDiagnostic)?.status === "unavailable" ? "error" : "done",
            ms: event.ms ?? 0,
            detail: `命中 ${String(payload.hits ?? 0)} 条 · ${retrievalMessage(payload.retrieval as RetrievalDiagnostic)}`,
          });
          if (Array.isArray(payload.citations)) {
            setCitations(payload.citations as unknown as Citation[]);
          }
          break;
        case "tool_result":
          if (isToolResult(payload)) {
            setHitl(null);
            setStatus("running");
            setTools((prev) => [...prev.filter(item => item.step_id !== payload.step_id), payload]);
            patchStep("tools", {
              status: "done",
              ms: event.ms ?? 0,
              detail: `${payload.name} ${payload.ok ? "成功" : "失败"}`,
            });
          }
          break;
        case "hitl_request":
          if (isHitl(payload)) {
            setHitl({ tool: payload.tool, args: payload.args ?? {}, approval_id: payload.approval_id });
            setStatus("waiting");
            patchStep("tools", { status: "running", detail: "等待人工确认" });
          }
          break;
        case "token":
          setAnswer((prev) => prev + String(payload.delta ?? ""));
          setSteps((prev) => prev.map((step) => step.stage === "tools" && step.detail === "等待工具结果" ? { ...step, status: "done", detail: "未调用工具" } : step));
          patchStep("generate", { status: "running", detail: "流式生成中" });
          break;
        case "done":
          if (payload.plan) {
            setPlan((payload.plan as ExecutionPlan).steps);
            setSteps(prev => evidenceStages(prev, payload.plan as ExecutionPlan, payload.retrieval as RetrievalDiagnostic));
          }
          if (payload.retrieval) setRetrieval(payload.retrieval as RetrievalDiagnostic);
          setHitl(null);
          setStatus("done");
          patchStep("generate", { status: "done", ms: event.ms ?? 0, detail: "已完成" });
          if (typeof payload.answer === "string") setAnswer(payload.answer);
          if (Array.isArray(payload.citations)) {
            setCitations(payload.citations as unknown as Citation[]);
          }
          break;
        case "error":
          setStatus("error");
          setError(String(payload.message ?? "未知错误"));
          patchStep(stage, { status: "error", detail: String(payload.message ?? "失败") });
          break;
        default:
          break;
      }
    },
    [patchStep],
  );

  const start = useCallback(
    async (sessionId: string, query: string) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      seenEvents.current.clear();

      setRunId(null);
      setQuery(query);
      setPlan([]);
      setSteps(initialSteps());
      patchStep("plan", { status: "running", detail: "正在分析问题" });
      setAnswer("");
      setCitations([]);
      setRetrieval(null);
      setTools([]);
      setHitl(null);
      setError(null);
      setStatus("running");

      try {
        const run = await createRun(sessionId, query);
        if (controller.signal.aborted) {
          await abortRun(run.id).catch(() => undefined);
          return;
        }
        setRunId(run.id);
        window.localStorage.setItem("agentops:last-run-id", run.id);
        await streamRun(run.id, (event) => { if (!controller.signal.aborted) handleEvent(event); }, controller.signal);
      } catch (reason) {
        if (!controller.signal.aborted) reportError(reason);
      }
    },
    [handleEvent, patchStep, reportError],
  );

  const restore = useCallback((snapshot: RunSnapshot | null) => {
    controllerRef.current?.abort();
    seenEvents.current.clear();
    setQuery(snapshot?.query ?? "");
    setPlan(snapshot?.plan?.steps ?? []);
    if (!snapshot) {
      setRunId(null);
      setSteps(initialSteps());
      setAnswer("");
      setCitations([]);
      setRetrieval(null);
      setTools([]);
      setHitl(null);
      setError(null);
      setStatus("idle");
      window.localStorage.removeItem("agentops:last-run-id");
      return;
    }
    setRunId(snapshot.id);
    setAnswer(snapshot.answer ?? "");
    setCitations(snapshot.citations ?? []);
    setRetrieval(snapshot.retrieval ?? null);
    setTools(snapshot.tool_results ?? []);
    setSteps(
      initialSteps().map((step) => {
        if (step.stage === "plan" && snapshot.plan?.steps?.length) {
          return { ...step, status: "done", detail: "已恢复执行计划" };
        }
        if ((step.stage === "tools" || step.stage === "retrieve") && snapshot.plan?.steps?.length &&
            !snapshot.plan.steps.some(s => s.kind === (step.stage === "tools" ? "tool" : "retrieve"))) {
          return { ...step, status: "skipped", detail: "本次无需执行" };
        }
        if (step.stage === "retrieve" && snapshot.retrieval?.status) {
          return { ...step, status: snapshot.retrieval.status === "unavailable" ? "error" : "done", detail: retrievalMessage(snapshot.retrieval) };
        }
        if (step.stage === "tools" && snapshot.tool_results?.length) {
          return { ...step, status: "done", detail: "已恢复工具结果" };
        }
        if (step.stage === "generate" && snapshot.answer) {
          return {
            ...step,
            status: snapshot.status === "running" ? "running" : "done",
            detail: snapshot.status === "running" ? "执行中" : "已完成",
          };
        }
        return step;
      }),
    );
    if (snapshot.plan?.steps?.length) {
      setSteps(prev => evidenceStages(prev, snapshot.plan as ExecutionPlan));
    }
    setHitl(snapshot.approval?.approval_id ? snapshot.approval : null);
    setError(null);
    setStatus(snapshot.status === "failed" ? "error" : snapshot.status === "awaiting_approval" ? "waiting" : snapshot.status === "running" ? "running" : "done");
    window.localStorage.setItem("agentops:last-run-id", snapshot.id);
    if (snapshot.status === "running" || snapshot.status === "awaiting_approval") {
      const controller = new AbortController();
      controllerRef.current = controller;
      // Replayed events restore the live reply and approval card after refresh.
      setAnswer("");
      setTools([]);
      void streamRun(snapshot.id, (event) => { if (!controller.signal.aborted) handleEvent(event); }, controller.signal)
        .catch((reason) => { if (!controller.signal.aborted) reportError(reason); });
    }
  }, [handleEvent, reportError]);

  const stop = useCallback(async () => {
    controllerRef.current?.abort();
    if (runId) await abortRun(runId).catch(() => undefined);
    setStatus((prev) => (prev === "running" ? "done" : prev));
  }, [runId]);

  const approve = useCallback(
    async (ok: boolean, args?: Record<string, unknown>) => {
      if (!runId) return;
      controllerRef.current?.abort();
      setError(null);
      const controller = new AbortController();
      controllerRef.current = controller;
      let resumed = false;
      try {
        await resumeRun(runId, ok, args, hitl?.approval_id);
        if (controller.signal.aborted) return;
        resumed = true;
        setHitl(null);
        setStatus("running");
        patchStep("tools", { status: "running", detail: ok ? "已确认，继续执行" : "已拒绝" });
        await streamRun(runId, (event) => { if (!controller.signal.aborted) handleEvent(event); }, controller.signal);
      } catch (reason) {
        if (!controller.signal.aborted) {
          if (!resumed && hitl) {
            setHitl(hitl);
            setStatus("waiting");
            setError(reason instanceof Error ? reason.message : "确认失败，请重试");
          } else reportError(reason);
        }
      }
    },
    [handleEvent, hitl, patchStep, reportError, runId],
  );

  const totalMs = useMemo(() => steps.reduce((sum, step) => sum + step.ms, 0), [steps]);

  return {
    runId,
    query,
    plan,
    steps,
    answer,
    citations,
    retrieval,
    tools,
    hitl,
    status,
    error,
    totalMs,
    start,
    restore,
    stop,
    approve,
  };
}
