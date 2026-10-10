import type { Citation, RetrievalDiagnostic } from "./types";

export function citationId(citation: Citation): string {
  return citation.citation_id || citation.chunk_id;
}

export function answerParts(answer: string, citations: Citation[]): Array<{ text: string; citation?: Citation }> {
  const known = new Map(citations.map((citation) => [citationId(citation), citation]));
  return answer.split(/(\[[^\]]+\])/g).map((text) => {
    const match = /^\[([^\]]+)\]$/.exec(text);
    return { text, citation: match ? known.get(match[1]) : undefined };
  });
}

export function sourceLink(source?: string): string | null {
  if (!source) return null;
  try {
    const url = new URL(source);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}

export function retrievalMessage(diagnostic?: RetrievalDiagnostic | null): string {
  if (!diagnostic?.status) return "该运行未记录检索诊断，无法判断历史空引用的原因。";
  if (diagnostic.mode === "echo") return "echo 演示模式未执行知识检索。使用 graph 模式并入库文档后重试。";
  const reasons: Record<string, string> = {
    database_missing: "未配置数据库，无法检索知识库。",
    identity_missing: "缺少用户身份，未检索知识库。",
    retrieval_error: "检索服务异常，请检查数据库或模型服务后重试。",
    database_error: "数据库查询失败，暂时无法读取知识库。请稍后重试或检查数据库连接。",
    clarification: "问题信息不足，尚未执行检索。请补充具体问题。",
    empty_library: "当前账号没有可检索的文档。请先入库相关资料。",
    no_match: "已执行检索，未找到相关片段。请补充文档或调整问题。",
    matched: "已检索到当前账号的文档片段。",
    not_started: "尚未执行检索。",
  };
  const warnings: Record<string, string> = {
    embedding_error: "向量化服务异常，已使用关键词检索；语义召回可能不完整。",
    rerank_error: "重排服务异常，已保留原始检索排序。",
  };
  const details = (diagnostic.warnings ?? []).map(reason => warnings[reason]).filter(Boolean);
  return `graph 模式 · ${reasons[diagnostic.reason ?? ""] ?? "暂无检索结果。"}${details.length ? ` ${details.join(" ")}` : ""}`;
}
