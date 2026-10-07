"use client";

import { motion } from "framer-motion";
import { ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useState } from "react";

export default function ApprovalCard({
  tool,
  args,
  onResolve,
}: {
  tool: string;
  args: Record<string, unknown>;
  onResolve: (ok: boolean, args: Record<string, unknown>) => void;
}) {
  const [draft, setDraft] = useState<Record<string, unknown>>(args);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="glass border-danger/40 p-4 shadow-glow"
    >
      <div className="flex items-center gap-2">
        <ShieldAlert size={16} className="text-danger" />
        <span className="subheading">高危操作待确认</span>
        <span className="pill border-danger/40 text-danger">{tool}</span>
      </div>

      <p className="mt-2 text-xs text-muted">
        该操作会写入外部系统，Agent 已挂起等待你的决定。参数可修改后再执行。
      </p>

      <div className="mt-3 space-y-2">
        {Object.entries(draft).filter(([key]) => key !== "idempotency_key").map(([key, value]) => (
          <label key={key} className="block">
            <span className="text-[11px] text-muted">{tool === "create_ticket" ? ({ title: "标题", detail: "描述", severity: "优先级" } as Record<string, string>)[key] ?? key : key}</span>
            {tool === "create_ticket" && key === "severity" ? (
              <select value={String(value)} onChange={(event) => setDraft((prev) => ({ ...prev, severity: event.target.value }))} className="mt-1 w-full rounded-lg border border-white/10 bg-ink-900 px-3 py-2 text-xs text-white">
                {["P0", "P1", "P2", "P3"].map((priority) => <option key={priority}>{priority}</option>)}
              </select>
            ) : tool === "create_ticket" && key === "detail" ? (
              <textarea value={String(value ?? "")} maxLength={20000} rows={3} onChange={(event) => setDraft((prev) => ({ ...prev, detail: event.target.value }))} className="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/80 px-3 py-2 text-xs text-white focus:border-brand-indigo" />
            ) : <input
              value={String(value ?? "")}
              maxLength={tool === "create_ticket" && key === "title" ? 300 : undefined}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, [key]: event.target.value }))
              }
              className="mt-1 w-full rounded-lg border border-white/10 bg-ink-900/80 px-3 py-2 text-xs text-white outline-none transition focus:border-brand-indigo"
            />}
          </label>
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => onResolve(true, draft)}
          disabled={tool === "create_ticket" && !String(draft.title ?? "").trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-gradient px-3 py-2 text-xs font-medium text-ink-900 transition hover:opacity-90"
        >
          <ShieldCheck size={13} />
          确认执行
        </button>
        <button
          onClick={() => onResolve(false, draft)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs text-muted transition hover:border-danger/50 hover:text-danger"
        >
          <X size={13} />
          拒绝并继续
        </button>
      </div>
    </motion.div>
  );
}
