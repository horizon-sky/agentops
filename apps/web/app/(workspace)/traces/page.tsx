"use client";

import { Play, Radio, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchTrace } from "@/lib/api";
import type { TraceNode } from "@/lib/types";
import { useRun } from "@/lib/useRun";

const STAGE_STYLE: Record<string, string> = {
  plan: "border-brand-indigo/50 text-brand-indigo",
  retrieve: "border-brand-cyan/50 text-brand-cyan",
  tools: "border-warning/50 text-warning",
  generate: "border-success/50 text-success",
};

function flatten(nodes: TraceNode[], depth = 0): Array<{ node: TraceNode; depth: number }> {
  const rows: Array<{ node: TraceNode; depth: number }> = [];
  for (const node of nodes) {
    rows.push({ node, depth });
    if (node.children?.length) rows.push(...flatten(node.children, depth + 1));
  }
  return rows;
}

export default function TraceReplay() {
  const run = useRun();
  const [runId, setRunId] = useState(run.runId ?? "");
  const [nodes, setNodes] = useState<TraceNode[]>([]);
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    setRunId(run.runId ?? "");
  }, [run.runId]);

  const load = async () => {
    if (!runId) return;
    const trace = await fetchTrace(runId);
    setNodes(trace);
    setCursor(trace.length ? 1 : 0);
  };

  const rows = flatten(nodes);
  const visible = rows.slice(0, cursor);

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="space-y-4">
        <div className="glass p-4">
          <div className="mb-3 flex items-center gap-2">
            <Radio size={14} className="text-brand-cyan" />
            <span className="subheading">选择一次执行</span>
          </div>
          <input
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            placeholder="run_id（执行任务后自动填充）"
            className="w-full rounded-lg border border-white/10 bg-ink-900/80 px-3 py-2 text-xs text-white outline-none transition focus:border-brand-indigo"
          />
          <div className="mt-3 flex gap-2">
            <button
              onClick={load}
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand-gradient px-3 py-2 text-xs font-medium text-ink-900 transition hover:opacity-90"
            >
              <Play size={12} />
              加载 Trace
            </button>
            <button
              onClick={() => setCursor(rows.length)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs text-muted transition hover:text-white"
            >
              <RotateCcw size={12} />
              播放到底
            </button>
          </div>
        </div>

        <div className="glass p-4">
          <div className="mb-2 text-xs text-muted">
            播放进度 {cursor} / {rows.length}
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(1, rows.length)}
            value={cursor}
            onChange={(event) => setCursor(Number(event.target.value))}
            className="w-full accent-brand-indigo"
          />
        </div>
      </div>

      <div className="glass p-4">
        <div className="subheading mb-3">Span 回放</div>
        {visible.length === 0 ? (
          <p className="text-xs text-muted">
            暂无 Trace。执行一次任务后点击「加载 Trace」，可按阶段逐步回放并定位失败点。
          </p>
        ) : (
          <div className="space-y-2">
            {visible.map(({ node, depth }) => (
              <div
                key={node.id}
                style={{ marginLeft: depth * 16 }}
                className={`rounded-xl border p-3 ${
                  node.status === "error" ? "border-danger/50 bg-danger/10" : "border-white/10"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`pill ${STAGE_STYLE[node.stage] ?? ""}`}>{node.stage}</span>
                  <span className="text-sm text-white">{node.name}</span>
                  <span className="ml-auto font-mono text-[11px] text-muted">{node.ms} ms</span>
                </div>
                <pre className="mt-2 max-h-32 overflow-auto rounded-lg border border-white/10 bg-ink-900/70 p-2 text-[11px] text-white/70">
                  {JSON.stringify(node.outputs ?? {}, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
