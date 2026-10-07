"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { abortRun, createRun, resumeRun, streamRun } from "./api";
import { isHitl, isToolResult } from "./api";
import type { AgentEvent, Citation, RunSnapshot, Stage, ToolResultPayload } from "./types";

export interface TimelineStep {
  stage: Stage;
  label: string;
  status: "pending" | "running" | "done" | "error";
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

export function useRun() {
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<TimelineStep[]>(initialSteps);
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [tools, setTools] = useState<ToolResultPayload[]>([]);
  const [hitl, setHitl] = useState<{ tool: string; args: Record<string, unknown> } | null>(null);
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
          patchStep("plan", {
            status: "done",
            ms: event.ms ?? 0,
            detail: Array.isArray(payload.steps)
              ? (payload.steps as string[]).join(" → ")
              : `意图 ${String(payload.intent ?? "-")}`,
          });
          break;
        case "retrieve":
          patchStep("retrieve", {
            status: "done",
            ms: event.ms ?? 0,
            detail: `命中 ${String(payload.hits ?? 0)} 条 · ${String(payload.note ?? "")}`,
          });
          if (Array.isArray(payload.citations)) {
            setCitations(payload.citations as unknown as Citation[]);
          }
          break;
        case "tool_result":
          if (isToolResult(payload)) {
            setHitl(null);
            setStatus("running");
            setTools((prev) => [...prev, payload]);
            patchStep("tools", {
              status: "done",
              ms: event.ms ?? 0,
              detail: `${payload.name} ${payload.ok ? "成功" : "失败"}`,
            });
          }
          break;
        case "hitl_request":
          if (isHitl(payload)) {
            setHitl({ tool: payload.tool, args: payload.args ?? {} });
            setStatus("waiting");
            patchStep("tools", { status: "running", detail: "等待人工确认" });
          }
          break;
        case "token":
          setAnswer((prev) => prev + String(payload.delta ?? ""));
          patchStep("generate", { status: "running", detail: "流式生成中" });
          break;
        case "done":
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

      setSteps(initialSteps());
      setAnswer("");
      setCitations([]);
      setTools([]);
      setHitl(null);
      setError(null);
      setStatus("running");

      try {
        const run = await createRun(sessionId, query);
        if (controller.signal.aborted) return;
        setRunId(run.id);
        window.localStorage.setItem("agentops:last-run-id", run.id);
        await streamRun(run.id, handleEvent, controller.signal);
      } catch (reason) {
        if (!controller.signal.aborted) reportError(reason);
      }
    },
    [handleEvent, reportError],
  );

  const restore = useCallback((snapshot: RunSnapshot | null) => {
    if (!snapshot) {
      setRunId(null);
      setSteps(initialSteps());
      setAnswer("");
      setCitations([]);
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
    setTools(snapshot.tool_results ?? []);
    setSteps(
      initialSteps().map((step) => {
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
    setHitl(null);
    setError(null);
    setStatus(snapshot.status === "failed" ? "error" : snapshot.status === "awaiting_approval" ? "waiting" : snapshot.status === "running" ? "running" : "done");
    window.localStorage.setItem("agentops:last-run-id", snapshot.id);
  }, []);

  const stop = useCallback(async () => {
    controllerRef.current?.abort();
    if (runId) await abortRun(runId).catch(() => undefined);
    setStatus((prev) => (prev === "running" ? "done" : prev));
  }, [runId]);

  const approve = useCallback(
    async (ok: boolean, args?: Record<string, unknown>) => {
      if (!runId) return;
      controllerRef.current?.abort();
      setHitl(null);
      setStatus("running");
      patchStep("tools", { status: "running", detail: ok ? "已确认，继续执行" : "已拒绝" });
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        await resumeRun(runId, ok, args);
        if (controller.signal.aborted) return;
        await streamRun(runId, handleEvent, controller.signal);
      } catch (reason) {
        if (!controller.signal.aborted) reportError(reason);
      }
    },
    [handleEvent, patchStep, reportError, runId],
  );

  const totalMs = useMemo(() => steps.reduce((sum, step) => sum + step.ms, 0), [steps]);

  return {
    runId,
    steps,
    answer,
    citations,
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
