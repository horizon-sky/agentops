"use client";

import { ChevronDown, Loader2, Terminal } from "lucide-react";
import type { ReactNode } from "react";
import MessageContent from "@/components/MessageContent";
import type { Citation, PlanStep } from "@/lib/types";
import type { TimelineStep } from "@/lib/useRun";

export default function ConversationTurn({ query, answer, citations, status, plan = [], steps = [], children, onCitation, onInspect }: {
  query: string;
  answer: string;
  citations: Citation[];
  status: string;
  plan?: PlanStep[];
  steps?: TimelineStep[];
  children?: ReactNode;
  onCitation: (id: string) => void;
  onInspect: () => void;
}) {
  const busy = status === "running";
  const waiting = status === "waiting";
  const activity = steps.filter((step) => step.status !== "pending");
  const label = waiting ? "等待你确认操作" : busy ? "正在处理" : status === "error" ? "执行遇到问题" : "工作记录";

  return (
    <article className="conversation-turn">
      <div className="user-message"><span className="sr-only">你：</span>{query}</div>
      <div className="agent-message">
        <div className="agent-avatar"><Terminal size={16} /></div>
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex items-center gap-2"><span className="text-sm font-semibold">AgentOps</span><span className="text-[11px] text-muted">助手</span></div>
          <details className="agent-activity">
            <summary>
              {busy ? <Loader2 size={13} className="animate-spin" /> : <ChevronDown size={13} className="activity-chevron" />}
              {label}
              {citations.length ? <span className="ml-auto text-[11px]">{citations.length} 条参考资料</span> : null}
            </summary>
            <div className="activity-body">
              {plan.length ? <ol className="list-decimal space-y-1 pl-4">{plan.map(step => <li key={step.id}>{step.goal}</li>)}</ol> : null}
              {activity.length ? <div className="mt-3 space-y-2">{activity.map((step) => <p key={step.stage}><span className="mr-2 text-white/80">{step.label}</span>{step.detail}</p>)}</div> : <p>此记录未保存工作过程，可查看右侧资料和工具结果。</p>}
              <button type="button" onClick={onInspect} className="mt-3 text-xs text-white/80 underline underline-offset-4">查看执行详情</button>
            </div>
          </details>
          {answer ? <MessageContent text={answer} citations={citations} onCitation={onCitation} /> : <p role="status" className="mt-4 text-sm text-muted">{waiting ? "操作尚未执行，请核对下方内容。" : busy ? "正在检索资料并处理你的问题…" : status === "error" ? "未能完成回答，请查看错误提示。" : "本次执行未生成回复。"}</p>}
          {children}
          {answer && busy ? <span className="reply-cursor" aria-label="正在生成回复" /> : null}
          {answer && !busy && !waiting ? <div className="reply-footer"><button type="button" onClick={onInspect}>查看资料与工具结果</button></div> : null}
        </div>
      </div>
    </article>
  );
}
