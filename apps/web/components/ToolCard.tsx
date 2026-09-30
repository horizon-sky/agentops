"use client";

import { motion } from "framer-motion";
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

export default function ToolCard({ item, index }: { item: ToolResultPayload; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="glass glass-hover p-3"
    >
      <div className="flex items-center gap-2">
        <Wrench size={14} className="text-brand-cyan" />
        <span className="text-sm font-medium text-white">{item.name}</span>
        <span className={`pill ${RISK_STYLE[item.risk ?? "read"]}`}>
          {item.risk === "high" ? <ShieldCheck size={11} /> : null}
          {RISK_LABEL[item.risk ?? "read"]}
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted">{item.ms ?? 0} ms</span>
      </div>

      <div className="mt-2 grid gap-2 text-[11px]">
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
    </motion.div>
  );
}
