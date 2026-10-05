"use client";

import { BarChart3, Gauge, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchEvalReport } from "@/lib/api";

const METRIC_META = [
  { key: "task_success_rate", label: "任务成功率", unit: "%" },
  { key: "tool_accuracy", label: "工具准确率", unit: "%" },
  { key: "recall_at_5", label: "Recall@5", unit: "%" },
  { key: "p95_latency_ms", label: "P95 延迟", unit: "ms" },
  { key: "cost_per_task", label: "单任务成本", unit: "¥" },
] as const;

const VERSION_ROWS = [
  { version: "v1 · 基线", success: 62, recall: 54, p95: 9200, note: "纯向量检索 + 无自审" },
  { version: "v2 · +混合检索", success: 74, recall: 71, p95: 8600, note: "BM25 + RRF 融合" },
  { version: "v3 · +Rerank", success: 83, recall: 82, p95: 8100, note: "Top5 重排" },
  { version: "v4 · +工具权限与 HITL", success: 88, recall: 83, p95: 7900, note: "高危写操作人工确认" },
];

export default function EvalDashboard() {
  const [metrics, setMetrics] = useState<Record<string, number | string>>({});

  useEffect(() => {
    fetchEvalReport()
      .then((report) => setMetrics(report.metrics ?? {}))
      .catch(() => setMetrics({}));
  }, []);

  const hasData = Object.keys(metrics).length > 0;

  const bars = useMemo(
    () =>
      METRIC_META.map((meta) => ({
        label: meta.label,
        value: hasData ? Number(metrics[meta.key] ?? 0) : 0,
      })),
    [hasData, metrics],
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {METRIC_META.map((meta) => (
          <div key={meta.key} className="glass glass-hover p-4">
            <div className="flex items-center gap-2 text-xs text-muted">
              <Gauge size={13} className="text-brand-cyan" />
              {meta.label}
            </div>
            <div className="mt-2 text-2xl font-semibold text-white">
              {hasData ? String(metrics[meta.key]) : "—"}
              <span className="ml-1 text-xs font-normal text-muted">{meta.unit}</span>
            </div>
            <div className="mt-1 text-[11px] text-muted">
              {hasData ? "来自 evals/report.json" : "运行评测后填入"}
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="glass p-4">
          <div className="mb-3 flex items-center gap-2">
            <BarChart3 size={14} className="text-brand-indigo" />
            <span className="subheading">当前版本指标</span>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bars}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis dataKey="label" stroke="#9AA5B8" fontSize={11} />
                <YAxis stroke="#9AA5B8" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: "#141A24",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                  {bars.map((entry, index) => (
                    <Cell key={index} fill={index % 2 ? "#22D3EE" : "#6366F1"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="glass p-4">
          <div className="mb-3 flex items-center gap-2">
            <TrendingUp size={14} className="text-success" />
            <span className="subheading">版本迭代趋势</span>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={VERSION_ROWS}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis dataKey="version" stroke="#9AA5B8" fontSize={11} />
                <YAxis stroke="#9AA5B8" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: "#141A24",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="success" name="成功率 %" stroke="#6366F1" strokeWidth={2} />
                <Line type="monotone" dataKey="recall" name="Recall@5 %" stroke="#22D3EE" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="glass overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-white/[0.03] text-muted">
            <tr>
              <th className="px-4 py-3 font-medium">版本</th>
              <th className="px-4 py-3 font-medium">成功率</th>
              <th className="px-4 py-3 font-medium">Recall@5</th>
              <th className="px-4 py-3 font-medium">P95 延迟</th>
              <th className="px-4 py-3 font-medium">变更说明</th>
            </tr>
          </thead>
          <tbody>
            {VERSION_ROWS.map((row) => (
              <tr key={row.version} className="border-t border-white/5 text-white/85">
                <td className="px-4 py-3">{row.version}</td>
                <td className="px-4 py-3 font-mono">{row.success}%</td>
                <td className="px-4 py-3 font-mono">{row.recall}%</td>
                <td className="px-4 py-3 font-mono">{row.p95} ms</td>
                <td className="px-4 py-3 text-muted">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-white/5 px-4 py-2 text-[11px] text-muted">
          表中数值需在 M6 运行 <span className="font-mono">uv run python -m evals.runner</span> 后替换为实测值，
          禁止预估。
        </div>
      </div>
    </div>
  );
}
