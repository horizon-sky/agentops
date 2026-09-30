"use client";

import { Coins, Timer } from "lucide-react";
import type { TimelineStep } from "@/lib/useRun";

const STAGE_COLOR: Record<string, string> = {
  plan: "bg-brand-indigo",
  retrieve: "bg-brand-cyan",
  tools: "bg-warning",
  generate: "bg-success",
};

export default function CostBar({
  steps,
  totalMs,
}: {
  steps: TimelineStep[];
  totalMs: number;
}) {
  const max = Math.max(1, ...steps.map((step) => step.ms));

  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-center gap-2">
        <Timer size={14} className="text-brand-cyan" />
        <span className="subheading">耗时瀑布</span>
        <span className="pill">
          <Coins size={11} />
          单任务分段统计
        </span>
      </div>

      <div className="space-y-2">
        {steps.map((step) => (
          <div key={step.stage} className="flex items-center gap-3">
            <span className="w-10 shrink-0 text-xs text-muted">{step.label}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
              <div
                className={`h-full rounded-full ${STAGE_COLOR[step.stage]} transition-all duration-500`}
                style={{ width: `${Math.max(2, (step.ms / max) * 100)}%` }}
              />
            </div>
            <span className="w-16 shrink-0 text-right font-mono text-[11px] text-white/80">
              {step.ms} ms
            </span>
          </div>
        ))}
      </div>

      <div className="mt-3 border-t border-white/10 pt-3 text-[11px] text-muted">
        端到端 {totalMs} ms · Token 与成本统计在接入 Trace 后展示
      </div>
    </div>
  );
}
