"use client";

import { AlertTriangle, ShieldCheck, Wrench } from "lucide-react";
import type { ToolResultPayload } from "@/lib/types";

const RISK_STYLE: Record<string, string> = {
  read: "border-success/40 text-success",
  write: "border-warning/40 text-warning",
  high: "border-danger/50 text-danger",
};

const RISK_LABEL: Record<string, string> = {
  read: "只读",
  write: "写入",
  high: "高危·需确认",
};

const TOOL_LABEL: Record<string, string> = {
  search_code: "搜索项目源码",
  query_metrics: "查询样例指标",
  create_ticket: "创建工单",
  draft_report: "生成报告草稿",
};

export default function ToolCard({ item }: { item: ToolResultPayload; index: number }) {
  return (
    <div className="glass p-3">
      <div className="flex items-center gap-2">
        <Wrench size={14} className="text-brand-cyan" />
        <span className="text-xs font-medium text-white">{TOOL_LABEL[item.name] ?? item.name}</span>
        <span className={`pill ${RISK_STYLE[item.risk ?? "read"]}`}>
          {item.risk === "high" ? <ShieldCheck size={11} /> : null}
          {RISK_LABEL[item.risk ?? "read"]}
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted">{item.ms ?? 0} ms</span>
      </div>

      {item.name === "query_metrics" ? <p className="mt-2 text-[11px] text-warning">演示数据，不能用于判断真实业务故障。</p> : null}
      {item.name === "search_code" ? <p className="mt-2 text-[11px] text-muted">搜索范围为 AgentOps 项目源码。</p> : null}

      <details className="mt-3 text-[11px]">
        <summary className="cursor-pointer text-muted">{item.ok ? "调用成功 · 查看详情" : "调用失败 · 查看详情"}</summary>
        <div className="mt-2 grid gap-2">
        <div>
          <div className="mb-1 text-muted">入参</div>
          <pre className="overflow-x-auto rounded-lg border border-white/10 bg-ink-900/70 p-2 text-white/80">
            {JSON.stringify(item.args ?? {}, null, 2)}
          </pre>
        </div>
        <div>
          <div className="mb-1 text-muted">出参</div>
          {item.ok ? (
            <pre className="max-h-40 overflow-auto rounded-lg border border-white/10 bg-ink-900/70 p-2 text-white/80">
              {JSON.stringify(item.output ?? {}, null, 2)}
            </pre>
          ) : (
            <div className="flex items-center gap-2 rounded-lg border border-danger/40 bg-danger/10 p-2 text-danger">
              <AlertTriangle size={12} />
              {item.error ?? "工具调用失败"}
            </div>
          )}
        </div>
        </div>
      </details>
      {!item.ok ? <p role="status" className="mt-2 break-words text-xs text-danger">{item.error ?? "工具调用失败"}</p> : null}
    </div>
  );
}
