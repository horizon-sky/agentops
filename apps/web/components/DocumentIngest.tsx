"use client";

import { useState } from "react";
import { ingestDocument } from "@/lib/api";

const FIELD = "mt-1 w-full rounded-lg border border-white/10 bg-ink-900 px-3 py-2 text-xs text-white focus:border-brand-indigo focus:outline-none";

export default function DocumentIngest() {
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError("");
    setMessage("");
    if (new TextEncoder().encode(content).length > 1_000_000) { setError("正文不能超过 1 MB"); return; }
    setBusy(true);
    try {
      const result = await ingestDocument({ title: title.trim(), source: source.trim(), content });
      setMessage(`入库成功：${result.chunks} 个片段，${result.embedded} 个已向量化。${result.embedded === 0 ? "当前可使用关键词检索。" : ""}请重新提问以检索这些资料。`);
      setTitle(""); setSource(""); setContent("");
    } catch (e) { setError(e instanceof Error ? e.message : "入库失败"); }
    finally { setBusy(false); }
  };
  return <details className="glass document-ingest p-4">
    <summary className="cursor-pointer text-sm text-white">入库参考文档</summary>
    <p className="mt-2 text-xs leading-relaxed text-muted">粘贴处理规范或参考手册，供当前账号检索。来源链接用于溯源，请同时填写正文。</p>
    <form onSubmit={submit} className="mt-3 space-y-3">
      <label className="block text-xs text-muted">标题<input required maxLength={300} disabled={busy} value={title} onChange={(e) => setTitle(e.target.value)} className={FIELD} /></label>
      <label className="block text-xs text-muted">来源（选填）<input maxLength={500} disabled={busy} value={source} onChange={(e) => setSource(e.target.value)} placeholder="文档链接或来源说明" className={FIELD} /></label>
      <label className="block text-xs text-muted">正文<textarea required rows={7} disabled={busy} value={content} onChange={(e) => setContent(e.target.value)} placeholder="支持纯文本与 Markdown" className={FIELD} /></label>
      {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
      {message ? <p role="status" className="text-xs leading-relaxed text-success">{message}</p> : null}
      <button disabled={busy || !title.trim() || !content.trim()} className="rounded-lg bg-brand-gradient px-3 py-2 text-xs font-medium text-ink-900 disabled:opacity-40">{busy ? "入库中…" : "入库文档"}</button>
    </form>
  </details>;
}
