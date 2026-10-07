"use client";

import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { TimelineStep } from "@/lib/useRun";

const STATUS_STYLE: Record<TimelineStep["status"], string> = {
  pending: "border-white/10 text-muted",
  running: "border-brand-cyan/60 text-brand-cyan",
  done: "border-success/50 text-success",
  error: "border-danger/60 text-danger",
};

function StatusIcon({ status }: { status: TimelineStep["status"] }) {
  if (status === "done") return <CheckCircle2 size={14} />;
  if (status === "running") return <Loader2 size={14} className="animate-spin" />;
  if (status === "error") return <XCircle size={14} />;
  return <Circle size={14} />;
}

export default function Timeline({
  steps,
  totalMs,
}: {
  steps: TimelineStep[];
  totalMs: number;
}) {
  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="subheading">执行链路</div>
        <span className="pill">总耗时 {totalMs} ms</span>
      </div>

      <div className="relative space-y-2">
        <div className="absolute left-[13px] top-3 bottom-3 w-px bg-gradient-to-b from-brand-indigo/60 via-brand-cyan/40 to-transparent" />
        {steps.map((step) => (
          <div
            key={step.stage}
            className="relative flex items-start gap-3 rounded-xl px-1 py-1.5"
          >
            <div
              className={`relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-ink-900 ${STATUS_STYLE[step.status]}`}
            >
              <StatusIcon status={step.status} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white">{step.label}</span>
                <span className="font-mono text-[11px] text-muted">{step.ms} ms</span>
              </div>
              <div className="mt-1 break-words text-xs leading-5 text-muted">{step.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
