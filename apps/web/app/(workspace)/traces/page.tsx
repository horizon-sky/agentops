"use client";

import { AlertCircle, Check, ChevronRight, Play, Radio, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchTrace } from "@/lib/api";
import type { TraceNode } from "@/lib/types";
import { useRun } from "@/lib/useRun";

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setRunId(run.runId ?? window.localStorage.getItem("agentops:last-run-id") ?? "");
  }, [run.runId]);

  useEffect(() => {
    const saved = window.localStorage.getItem("agentops:last-run-id");
    if (!runId && saved) setRunId(saved);
  }, [runId]);

  const load = async () => {
    if (!runId) return;
    setLoading(true);
    setError("");
    try {
      const trace = await fetchTrace(runId);
      setNodes(trace);
      setCursor(trace.length ? 1 : 0);
    } catch (reason) {
      setNodes([]);
      setCursor(0);
      setError(reason instanceof Error ? reason.message : "Trace 加载失败");
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (runId) void load();
    // 仅在恢复最近一次运行时自动加载 Trace。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const rows = flatten(nodes);
  const visible = rows.slice(0, cursor);

  return (
    <main className="ops-page traces-page">
      <header className="ops-page-header">
        <div>
          <p className="ops-kicker">工作台 · 可观测性</p>
          <h1>Trace 回放</h1>
          <p className="ops-page-description">按阶段复查一次执行，定位检索、工具或生成环节的异常。</p>
        </div>
        <div className="trace-header-meta"><span className={nodes.length ? "trace-live is-ready" : "trace-live"}>{nodes.length ? <Check size={13} /> : <Radio size={13} />}{nodes.length ? "已加载" : "等待 Trace"}</span>{runId ? <code>{runId}</code> : null}</div>
      </header>
      <div className="trace-workspace">
      <aside className="trace-controls">
        <section className="ops-panel trace-control-panel">
          <div className="trace-panel-heading"><div><p className="ops-kicker">回放对象</p><h2>选择一次执行</h2></div><Radio size={17} /></div>
          <input
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            placeholder="输入 run_id，或先在工作台执行任务"
            className="trace-input"
          />
          <div className="trace-control-actions">
            <button
              onClick={() => void load()}
              disabled={!runId || loading}
              className="ops-button ops-button-primary"
            >
              <Play size={14} />{loading ? "加载中…" : "加载 Trace"}
            </button>
            <button
              onClick={() => setCursor(rows.length)}
              disabled={!rows.length}
              className="ops-button ops-button-secondary"
            >
              <RotateCcw size={14} />播放到底
            </button>
          </div>
          {error ? <p role="alert" className="trace-error"><AlertCircle size={14} />{error}</p> : null}
        </section>
        <section className="ops-panel trace-progress-panel">
          <div className="trace-progress-copy"><span>播放进度</span><strong>{cursor} / {rows.length}</strong></div>
          <input
            type="range"
            min={0}
            max={Math.max(1, rows.length)}
            value={cursor}
            onChange={(event) => setCursor(Number(event.target.value))}
            className="trace-range"
          />
        </section>
        <p className="trace-hint">拖动进度条逐步展开 Span。点击「播放到底」查看完整执行树。</p>
      </aside>

      <section className="ops-panel trace-panel">
        <div className="trace-panel-heading"><div><p className="ops-kicker">执行树</p><h2>Span 回放</h2></div><span className="trace-count">{visible.length} / {rows.length} 已展开</span></div>
        {visible.length === 0 ? (
          <div className="ops-state trace-empty"><p>{error ? "无法显示这次执行" : "还没有可回放的 Trace"}</p><span>{error ? "请检查 run_id 后重试。" : "执行一次任务后加载 Trace，按阶段定位失败点。"}</span></div>
        ) : (
          <div className="trace-tree">
            {visible.map(({ node, depth }) => (
              <div
                key={node.id}
                style={{ marginLeft: depth * 16 }}
                className={`trace-row ${node.status === "error" ? "is-error" : ""}`}
              >
                <div className="trace-row-main">
                  <ChevronRight size={14} className="trace-row-chevron" />
                  <span className={`trace-stage trace-stage-${node.stage}`}>{node.stage}</span>
                  <span className="trace-node-name">{node.name}</span>
                  <span className="trace-node-ms">{node.ms} ms</span>
                </div>
                <div className="trace-row-meta"><span>{node.status === "error" ? "执行失败" : "已完成"}</span><span>{node.tokens ? `${node.tokens} tokens` : "无 token 记录"}</span><span>{node.cost ? `$${node.cost.toFixed(4)}` : "成本待接入"}</span></div>
                <details className="trace-output"><summary>查看输出</summary><pre>
                  {JSON.stringify(node.outputs ?? {}, null, 2)}
                </pre></details>
              </div>
            ))}
          </div>
        )}
      </section>
      </div>
    </main>
  );
}
