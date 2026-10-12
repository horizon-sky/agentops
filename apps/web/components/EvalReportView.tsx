"use client";

import { ClipboardCheck, RefreshCw } from "lucide-react";
import type { EvalReport } from "@/lib/types";

const METRICS = [
  { key: "task_success_rate", label: "任务成功率", unit: "%" },
  { key: "tool_accuracy", label: "工具准确率", unit: "%" },
  { key: "p50_latency_ms", label: "P50 延迟", unit: " ms" },
  { key: "p95_latency_ms", label: "P95 延迟", unit: " ms" },
  { key: "cases", label: "用例数", unit: "" },
  { key: "citation_skipped", label: "引用断言跳过数", unit: "" },
  { key: "recall_at_5", label: "Recall@5", unit: "%" },
  { key: "avg_tokens", label: "平均 Token", unit: "" },
  { key: "cost_per_task", label: "单任务成本", unit: " USD" },
] as const;

const STAGE_LABELS: Record<string, string> = {
  plan: "规划", retrieve: "检索", tools: "工具与审批", generate: "生成",
};

function measurement(value: number | null | undefined, unit: string): string {
  return value == null || !Number.isFinite(value) ? "未测量" : `${value}${unit}`;
}

function timestamp(value: string | null): string {
  if (!value) return "未记录";
  return new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Hong_Kong", hour12: false });
}

type Props = {
  report: EvalReport | null;
  loading: boolean;
  error: string;
  onReload: () => void;
};

export default function EvalReportView({ report, loading, error, onReload }: Props) {
  const reload = (label: string) => (
    <button type="button" onClick={onReload} disabled={loading}
      className="inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-sm text-white transition hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-cyan disabled:opacity-50">
      <RefreshCw size={14} aria-hidden="true" />{label}
    </button>
  );

  if (loading) return <div className="glass p-6" role="status">正在读取评测报告…</div>;
  if (error) return (
    <div className="glass space-y-4 p-6">
      <p role="alert" className="text-danger">{error}</p>{reload("重试")}
    </div>
  );
  if (!report || report.status === "empty") return (
    <section className="glass space-y-4 p-6">
      <ClipboardCheck size={24} className="text-muted" aria-hidden="true" />
      <h1 className="subheading">尚未发布评测报告</h1>
      <p className="max-w-2xl text-sm text-muted">完成独立环境评测并发布结果后，这里将展示最新一次报告。日常对话不会自动生成评测数据。</p>
      {reload("刷新")}
    </section>
  );

  const source = report.source;
  const failures = Object.entries(report.metrics.failure_stages ?? {}).filter(([, count]) => count > 0);
  const environment = source?.environment === "staging" ? "独立环境评测"
    : source?.environment === "ci" ? "CI 环境评测" : "本地环境评测";
  const retrieval = source?.configured_retrieval_mode === "hybrid" ? "混合检索"
    : source?.configured_retrieval_mode === "bm25" ? "BM25" : "无数据库检索";

  return (
    <div className="space-y-5">
      <section className="glass p-5 md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="subheading">最新评测报告</h1>
            <p className="mt-2 text-sm text-muted">完成于 {timestamp(report.generated_at)}（香港时间）</p>
          </div>
          {reload("刷新报告")}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="pill">{environment}</span>
          <span className="pill">{source?.llm_configured ? "已配置模型" : "离线降级"}</span>
          <span className="pill">检索配置：{retrieval}</span>
          <span className="pill">样例指标工具</span>
          {source?.code_dirty ? <span className="pill">含未提交源码修改</span> : null}
        </div>
        <p className="mt-4 max-w-3xl text-xs leading-6 text-muted">指标来自选定黄金集的规则断言，表示该测试环境的运行结果。指标查询工具使用样例数据，结果不代表生产实时监控或业务成功率。检索配置不代表每个用例实际采用的方式，运行时可能降级。</p>
        <dl className="mt-5 grid gap-x-8 gap-y-3 border-t border-white/10 pt-4 text-xs sm:grid-cols-2 lg:grid-cols-3">
          {[
            ["代码版本", report.git_sha], ["主模型版本", report.model_version],
            ["轻量模型版本", source?.cheap_model],
            ["Prompt 版本", report.prompt_version], ["黄金集版本", source?.golden_set_version],
            ["报告 ID", report.id],
            ["执行开关", source ? `路由 ${source.agent_flags.routing ? "开" : "关"} / 重试 ${source.agent_flags.retry ? "开" : "关"} / 动态计划 ${source.agent_flags.dynamic ? "开" : "关"}` : null],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-muted">{label}</dt>
              <dd className="mt-1 break-words text-white/85">{value || "未记录"}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="glass overflow-hidden" aria-label="实测指标">
        <dl className="grid sm:grid-cols-2 lg:grid-cols-3">
          {METRICS.map(({ key, label, unit }) => (
            <div key={key} className="border-b border-white/10 p-5">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className={`mt-2 tabular-nums ${report.metrics[key] == null ? "text-lg text-muted" : "text-2xl font-semibold text-white"}`}>
                {measurement(report.metrics[key], unit)}
              </dd>
            </div>
          ))}
        </dl>
        <p className="px-5 py-3 text-xs leading-6 text-muted">Recall@5 尚未完成相关文档标注；Token 与成本尚未接入实际计量。引用断言跳过表示未具备验证条件，不等于检索验证通过。</p>
      </section>

      <section className="glass p-5">
        <h2 className="subheading">失败阶段分布</h2>
        <p className="mt-2 text-xs text-muted">每个失败用例按首个未通过的阶段统计。</p>
        {failures.length ? (
          <table className="mt-4 w-full text-left text-sm">
            <thead className="text-xs text-muted"><tr>
              <th scope="col" className="pb-3 font-normal">阶段</th>
              <th scope="col" className="pb-3 text-right font-normal">失败用例数</th>
            </tr></thead>
            <tbody>{failures.map(([stage, count]) => (
              <tr key={stage} className="border-t border-white/10">
                <th scope="row" className="py-3 font-normal text-white/85">{STAGE_LABELS[stage] ?? stage}</th>
                <td className="py-3 text-right tabular-nums text-white">{count}</td>
              </tr>
            ))}</tbody>
          </table>
        ) : <p className="mt-4 text-sm text-muted">{report.metrics.failure_stages ? "本次没有失败用例。" : "失败阶段未记录。"}</p>}
      </section>
    </div>
  );
}
