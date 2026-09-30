"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { abortRun, createRun, resumeRun, streamRun } from "./api";
import { isHitl, isToolResult } from "./api";
import type { AgentEvent, Citation, Stage, ToolResultPayload } from "./types";

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

  const patchStep = useCallback((stage: Stage, patch: Partial<TimelineStep>) => {
    setSteps((prev) =>
      prev.map((step) => (step.stage === stage ? { ...step, ...patch } : step)),
    );
  }, []);

  const handleEvent = useCallback(
    (event: AgentEvent) => {
      const payload = event.payload ?? {};
      const stage = event.stage ?? "plan";
      patchStep(stage, { status: "running", detail: "执行中" });

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

      setSteps(initialSteps());
      setAnswer("");
      setCitations([]);
      setTools([]);
      setHitl(null);
      setError(null);
      setStatus("running");

      const run = await createRun(sessionId, query);
      setRunId(run.id);
      await streamRun(run.id, handleEvent, controller.signal).catch(() => undefined);
    },
    [handleEvent],
  );

  const stop = useCallback(async () => {
    controllerRef.current?.abort();
    if (runId) await abortRun(runId).catch(() => undefined);
    setStatus((prev) => (prev === "running" ? "done" : prev));
  }, [runId]);

  const approve = useCallback(
    async (ok: boolean, args?: Record<string, unknown>) => {
      if (!runId) return;
      setHitl(null);
      setStatus("running");
      patchStep("tools", { status: "running", detail: ok ? "已确认，继续执行" : "已拒绝" });
      await resumeRun(runId, ok, args).catch(() => undefined);
      const controller = new AbortController();
      controllerRef.current = controller;
      await streamRun(runId, handleEvent, controller.signal).catch(() => undefined);
    },
    [handleEvent, patchStep, runId],
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
    stop,
    approve,
  };
}
