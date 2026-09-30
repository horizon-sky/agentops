"use client";

import { FileText, Quote } from "lucide-react";
import type { Citation } from "@/lib/types";

export default function CitationPanel({
  citations,
  activeChunkId,
  onHover,
}: {
  citations: Citation[];
  activeChunkId: string | null;
  onHover: (chunkId: string | null) => void;
}) {
  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-center gap-2">
        <Quote size={14} className="text-brand-cyan" />
        <span className="subheading">引用溯源</span>
        <span className="pill">{citations.length} 条</span>
      </div>

      {citations.length === 0 ? (
        <p className="text-xs text-muted">
          暂无引用。检索接入后，回答中的每个结论都会带上可点击的原文锚点。
        </p>
      ) : (
        <div className="space-y-2">
          {citations.map((citation) => {
            const active = activeChunkId === citation.chunk_id;
            return (
              <div
                key={citation.chunk_id}
                onMouseEnter={() => onHover(citation.chunk_id)}
                onMouseLeave={() => onHover(null)}
                className={`cursor-pointer rounded-xl border p-3 transition ${
                  active
                    ? "border-brand-cyan/60 bg-brand-cyan/10 shadow-glow"
                    : "border-white/10 bg-white/[0.02] hover:border-white/20"
                }`}
              >
                <div className="flex items-center gap-2 text-[11px] text-muted">
                  <FileText size={11} />
                  <span className="font-mono text-brand-cyan">{citation.chunk_id}</span>
                  <span className="ml-auto">score {citation.score?.toFixed(3) ?? "-"}</span>
                </div>
                <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed text-white/80">
                  {citation.snippet || "（无摘要）"}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
