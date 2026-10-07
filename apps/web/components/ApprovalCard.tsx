"use client";

import { Check, ShieldCheck, X } from "lucide-react";
import { useState } from "react";

export default function ApprovalCard({ tool, args, onResolve }: {
  tool: string;
  args: Record<string, unknown>;
  onResolve: (ok: boolean, args: Record<string, unknown>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Record<string, unknown>>(args);
  const [submitting, setSubmitting] = useState(false);
  const ticket = tool === "create_ticket";

  const resolve = async (ok: boolean) => {
    if (submitting) return;
    setSubmitting(true);
    try { await onResolve(ok, draft); }
    finally { setSubmitting(false); }
  };

  return (
    <section className="approval-card" aria-label="人工确认">
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShieldCheck size={17} className="text-warning" />
        {ticket ? "确认创建工单" : "确认执行操作"}
        <span className="ml-auto text-[11px] font-normal text-muted">等待确认</span>
      </div>
      <p className="mt-2 text-xs leading-6 text-muted">
        {ticket ? "请核对标题、描述和优先级。确认后，这张工单将保存到工单总览。" : "请核对操作内容。确认后才会执行，你也可以拒绝。"}
      </p>
      <fieldset disabled={submitting} className="mt-4 space-y-3">
        {Object.entries(draft).filter(([key]) => key !== "idempotency_key").map(([key, value]) => (
          <label key={key} className="block text-xs text-muted">
            {ticket ? ({ title: "标题", detail: "描述", severity: "优先级" } as Record<string, string>)[key] ?? key : key}
            {ticket && key === "severity" ? (
              <select value={String(value)} onChange={(event) => setDraft((prev) => ({ ...prev, severity: event.target.value }))} className="approval-input">
                {["P0", "P1", "P2", "P3"].map((priority) => <option key={priority}>{priority}</option>)}
              </select>
            ) : ticket && key === "detail" ? (
              <textarea value={String(value ?? "")} maxLength={20000} rows={4} onChange={(event) => setDraft((prev) => ({ ...prev, detail: event.target.value }))} className="approval-input" />
            ) : (
              <input value={String(value ?? "")} maxLength={ticket && key === "title" ? 300 : undefined} onChange={(event) => setDraft((prev) => ({ ...prev, [key]: event.target.value }))} className="approval-input" />
            )}
          </label>
        ))}
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <button type="button" onClick={() => void resolve(false)} className="approval-deny"><X size={14} />拒绝操作</button>
          <button type="button" onClick={() => void resolve(true)} disabled={submitting || (ticket && !String(draft.title ?? "").trim())} className="approval-confirm"><Check size={14} />{submitting ? "正在提交…" : ticket ? "确认创建" : "确认执行"}</button>
        </div>
      </fieldset>
    </section>
  );
}
