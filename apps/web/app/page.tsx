"use client";

import { AlertTriangle, Bot, Sparkles, User } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ApprovalCard from "@/components/ApprovalCard";
import CitationPanel from "@/components/CitationPanel";
import Composer from "@/components/Composer";
import CostBar from "@/components/CostBar";
import SessionList from "@/components/SessionList";
import Timeline from "@/components/Timeline";
import ToolCard from "@/components/ToolCard";
import { createSession } from "@/lib/api";
import type { Session } from "@/lib/types";
import { useRun } from "@/lib/useRun";

const QUERY_SUGGESTIONS = [
  "订单服务昨晚 5xx 报警，帮我定位可能原因",
  "支付回调超时应该怎么排查？需要建单跟进",
  "知识库里关于数据库慢查询的处理规范是什么？",
];

export default function Workbench() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [hoveredChunk, setHoveredChunk] = useState<string | null>(null);
  const run = useRun();

  useEffect(() => {
    createSession("工单排查会话")
      .then((session) => {
        setSessions([session]);
        setActiveId(session.id);
      })
      .catch(() => undefined);
  }, []);

  const newSession = async () => {
    const session = await createSession(`工单排查 ${sessions.length + 1}`);
    setSessions((prev) => [session, ...prev]);
    setActiveId(session.id);
  };

  const answerWithAnchors = useMemo(() => {
    if (!run.answer) return null;
    const parts = run.answer.split(/(\[[^\]]+\])/g);
    return parts.map((part, index) => {
      const matched = /^\[([^\]]+)\]$/.exec(part);
      if (matched) {
        const chunkId = matched[1];
        return (
          <button
            key={index}
            onMouseEnter={() => setHoveredChunk(chunkId)}
            onMouseLeave={() => setHoveredChunk(null)}
            className={`mx-0.5 rounded px-1 font-mono text-[11px] transition ${
              hoveredChunk === chunkId
                ? "bg-brand-cyan/20 text-brand-cyan"
                : "bg-white/5 text-brand-cyan/80 hover:bg-brand-cyan/15"
            }`}
          >
            [{chunkId}]
          </button>
        );
      }
      return <span key={index}>{part}</span>;
    });
  }, [run.answer, hoveredChunk]);

  const submit = async (query: string) => {
    let sessionId = activeId;
    if (!sessionId) {
      const session = await createSession(query.slice(0, 20));
      setSessions((prev) => [session, ...prev]);
      setActiveId(session.id);
      sessionId = session.id;
    }
    await run.start(sessionId, query);
  };

  return (
    <div className="flex h-full gap-4">
      <SessionList
        sessions={sessions}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={newSession}
      />

      <main className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <Timeline steps={run.steps} totalMs={run.totalMs} />

            {run.status === "waiting" && run.hitl ? (
              <ApprovalCard
                tool={run.hitl.tool}
                args={run.hitl.args}
                onResolve={(ok, args) => run.approve(ok, args)}
              />
            ) : null}

            {run.error ? (
              <div className="glass flex items-center gap-2 border-danger/40 p-3 text-sm text-danger">
                <AlertTriangle size={14} />
                {run.error}
              </div>
            ) : null}

            <div className="glass min-h-[160px] p-4">
              <div className="mb-2 flex items-center gap-2">
                <Bot size={14} className="text-brand-cyan" />
                <span className="subheading">Agent 输出</span>
              </div>
              {run.answer ? (
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-white/90">
                  {answerWithAnchors}
                  {run.status === "running" ? (
                    <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-brand-cyan align-middle" />
                  ) : null}
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="flex items-center gap-2 text-sm text-muted">
                    <Sparkles size={14} className="text-brand-indigo" />
                    试试这些问题，观察执行链路与工具调用：
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {QUERY_SUGGESTIONS.map((item) => (
                      <button
                        key={item}
                        onClick={() => submit(item)}
                        className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-white/80 transition hover:border-brand-indigo hover:text-white"
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {run.tools.length > 0 ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <User size={14} className="text-muted" />
                  <span className="subheading">工具调用</span>
                </div>
                {run.tools.map((item, index) => (
                  <ToolCard key={`${item.name}-${index}`} item={item} index={index} />
                ))}
              </div>
            ) : null}
          </div>

          <div className="space-y-4">
            <CitationPanel
              citations={run.citations}
              activeChunkId={hoveredChunk}
              onHover={setHoveredChunk}
            />
            <CostBar steps={run.steps} totalMs={run.totalMs} />
          </div>
        </div>

        <div className="mt-auto">
          <Composer running={run.status === "running"} onSubmit={submit} onStop={run.stop} />
        </div>
      </main>
    </div>
  );
}
