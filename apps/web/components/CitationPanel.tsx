"use client";

import { FileText, Quote } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchChunk } from "@/lib/api";
import { citationId, retrievalMessage, sourceLink } from "@/lib/citations";
import type { ChunkPreview, Citation, RetrievalDiagnostic } from "@/lib/types";

export default function CitationPanel({ citations, activeChunkId, selectedId, retrieval, onHover, onSelect }: {
  citations: Citation[];
  activeChunkId: string | null;
  selectedId: string | null;
  retrieval: RetrievalDiagnostic | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}) {
  const [preview, setPreview] = useState<ChunkPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const selected = citations.find((citation) => citationId(citation) === selectedId);
  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    setError("");
    setLoading(false);
    if (selected) document.getElementById(`citation-${citationId(selected)}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (selected?.citation_id && selected.document_id) {
      setLoading(true);
      fetchChunk(selected.document_id, selected.citation_id)
        .then((value) => { if (!cancelled) setPreview(value); })
        .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "原文加载失败"); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }
    return () => { cancelled = true; };
  }, [selected, retry]);

  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-center gap-2"><Quote size={14} className="text-brand-cyan" /><h2 className="subheading">引用溯源</h2><span className="pill">{citations.length} 条</span></div>
      {citations.length === 0 ? <p className="text-xs leading-relaxed text-muted">{retrieval ? retrievalMessage(retrieval) : "暂无引用。入库相关资料后，在 graph 模式提问可检索原文。历史记录未提供诊断时，无法判断当时的检索原因。"}</p> : <div className="space-y-2">
        {citations.map((citation, index) => {
          const id = citationId(citation);
          const expanded = selectedId === id;
          const url = sourceLink(expanded && preview ? preview.source_url : citation.source_url);
          return <article key={`${id}-${index}`} id={`citation-${id}`} className={`rounded-xl border p-3 ${activeChunkId === id || expanded ? "border-brand-cyan/60 bg-brand-cyan/10" : "border-white/10 bg-white/[0.02]"}`}>
            <button type="button" aria-expanded={expanded} onClick={() => onSelect(expanded ? null : id)} onMouseEnter={() => onHover(id)} onMouseLeave={() => onHover(null)} className="w-full text-left focus-visible:outline focus-visible:outline-brand-cyan">
              <span className="flex items-center gap-2 text-xs text-white"><FileText size={12} /><span className="break-words">{citation.title || "历史引用"}</span><span className="ml-auto shrink-0 text-brand-cyan">{expanded ? "收起" : "查看原文"}</span></span>
              {citation.heading ? <span className="mt-1 block text-xs text-muted">章节：{citation.heading}</span> : null}
              <span className="mt-1 block break-all font-mono text-[10px] text-muted">{id}</span>
              <span className="mt-2 block line-clamp-4 text-xs leading-relaxed text-white/80">{citation.snippet || "（无摘要）"}</span>
            </button>
            <p className="mt-2 text-[11px] text-muted">检索方式：{citation.retrieval_method || citation.source || "未记录"} · score {citation.score?.toFixed(3) ?? "-"}</p>
            {citation.source_url ? <p className="mt-1 break-all text-[11px] text-muted">文档来源：{citation.source_url}</p> : null}
            {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-xs text-brand-cyan hover:underline">打开来源链接</a> : null}
            {expanded ? <div className="mt-3 border-t border-white/10 pt-3">
              {loading ? <p role="status" className="text-xs text-muted">正在加载原文…</p> : error ? <div role="alert" className="text-xs text-danger">{error}<button onClick={() => setRetry((n) => n + 1)} className="ml-2 underline">重试</button></div> : <>
                <p className="mb-2 text-xs text-muted">{preview ? "入库原文片段" : "历史引用仅保存了摘要，无法定位完整片段。"}</p>
                <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-white/90">{preview?.content ?? citation.snippet ?? "（无摘要）"}</p>
              </>}
            </div> : null}
          </article>;
        })}
      </div>}
    </div>
  );
}
