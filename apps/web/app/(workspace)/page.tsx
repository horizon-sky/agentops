"use client";

import { AlertCircle, BookOpen, ClipboardList, FileText, Loader2, PanelLeft, PanelRight, Terminal, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import ApprovalCard from "@/components/ApprovalCard";
import CitationPanel from "@/components/CitationPanel";
import Composer from "@/components/Composer";
import ConversationTurn from "@/components/ConversationTurn";
import CostBar from "@/components/CostBar";
import DocumentIngest from "@/components/DocumentIngest";
import SessionList from "@/components/SessionList";
import Timeline from "@/components/Timeline";
import ToolCard from "@/components/ToolCard";
import { createSession, listSessionRuns, listSessions } from "@/lib/api";
import type { RunSnapshot, Session } from "@/lib/types";
import { useRun } from "@/lib/useRun";

const QUERY_SUGGESTIONS = [
  { icon: BookOpen, title: "查询处理规范", description: "从已入库资料中查找依据", query: "知识库中有哪些问题处理规范？请整理关键步骤并引用原文；没有相关资料时请明确说明。" },
  { icon: FileText, title: "整理参考资料", description: "填写主题，提炼相关文档内容", query: "请根据知识库中与「填写文档主题」相关的资料，整理适用范围、关键流程和需要补充的信息，并引用原文。" },
  { icon: ClipboardList, title: "创建跟进工单", description: "核对内容，确认后再创建", query: "请创建一个 P2 工单：补充问题处理文档。描述：当前资料不足，需要收集相关手册和现场记录，具体原因待确认。" },
];

export default function Workbench() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [history, setHistory] = useState<RunSnapshot[]>([]);
  const [selectedRecord, setSelectedRecord] = useState<RunSnapshot | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<string | null>(null);
  const [hoveredChunk, setHoveredChunk] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [pageError, setPageError] = useState("");
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const followReply = useRef(true);
  const requestVersion = useRef(0);
  const run = useRun();
  const busy = run.status === "running" || run.status === "waiting";
  const locked = busy || loading || submitting;

  const restoreConversation = useCallback((records: RunSnapshot[]) => {
    setHistory(records.slice(1).reverse());
    setSelectedRecord(null);
    setSelectedCitation(null);
    setHoveredChunk(null);
    followReply.current = true;
    run.restore(records[0] ?? null);
  }, [run.restore]);

  useEffect(() => {
    const version = ++requestVersion.current;
    listSessions().then(async (items) => {
      if (requestVersion.current !== version) return;
      setSessions(items);
      setActiveId(items[0]?.id ?? null);
      const records = items[0] ? await listSessionRuns(items[0].id) : [];
      if (requestVersion.current === version) restoreConversation(records);
    }).catch((reason) => {
      if (requestVersion.current === version) setPageError(reason instanceof Error ? reason.message : "会话加载失败，请刷新重试");
    }).finally(() => {
      if (requestVersion.current === version) setLoading(false);
    });
    return () => { requestVersion.current++; };
  }, [restoreConversation]);

  useEffect(() => {
    if (followReply.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history, run.query, run.answer, run.status, run.plan, run.hitl]);

  useEffect(() => {
    if (!sessionsOpen && !detailsOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setSessionsOpen(false); setDetailsOpen(false); }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [sessionsOpen, detailsOpen]);

  const selectSession = async (sessionId: string) => {
    if (locked) return;
    const version = ++requestVersion.current;
    setLoading(true);
    setPageError("");
    setActiveId(sessionId);
    setDraft("");
    run.restore(null);
    setHistory([]);
    setSessionsOpen(false);
    setDetailsOpen(false);
    try {
      const records = await listSessionRuns(sessionId);
      if (requestVersion.current === version) restoreConversation(records);
    } catch (reason) {
      if (requestVersion.current === version) setPageError(reason instanceof Error ? reason.message : "会话加载失败，请重试");
    } finally {
      if (requestVersion.current === version) setLoading(false);
    }
  };

  const newSession = () => {
    if (locked) return;
    requestVersion.current++;
    setActiveId(null);
    setHistory([]);
    setSelectedRecord(null);
    setSelectedCitation(null);
    setDraft("");
    setPageError("");
    setSessionsOpen(false);
    setDetailsOpen(false);
    run.restore(null);
  };

  const submit = async (query: string) => {
    if (locked) return;
    setSubmitting(true);
    setPageError("");
    try {
      let sessionId = activeId;
      if (!sessionId) {
        const session = await createSession(query.slice(0, 40));
        setSessions((prev) => [session, ...prev]);
        setActiveId(session.id);
        sessionId = session.id;
      }
      if (run.query) {
        const record: RunSnapshot = {
          id: run.runId ?? "local-" + Date.now(),
          session_id: sessionId,
          query: run.query,
          answer: run.answer,
          status: run.status === "error" ? "failed" : "completed",
          citations: run.citations,
          retrieval: run.retrieval ?? undefined,
          tool_results: run.tools,
        };
        setHistory((prev) => [...prev, record]);
      }
      setSelectedRecord(null);
      setSelectedCitation(null);
      setHoveredChunk(null);
      followReply.current = true;
      const execution = run.start(sessionId, query);
      setSubmitting(false);
      await execution;
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "发送失败，请重试");
      setDraft(query);
    } finally { setSubmitting(false); }
  };

  const inspect = (record: RunSnapshot | null, citationId?: string) => {
    setSelectedRecord(record);
    setSelectedCitation(citationId ?? null);
    setHoveredChunk(null);
    setDetailsOpen(true);
  };
  const sourceRecord = selectedRecord;
  const citations = sourceRecord ? sourceRecord.citations ?? [] : run.citations;
  const toolResults = sourceRecord ? sourceRecord.tool_results ?? [] : run.tools;
  const retrieval = sourceRecord ? sourceRecord.retrieval ?? null : run.retrieval;
  const hasConversation = history.length > 0 || Boolean(run.query);
  const statusLabel = loading ? "加载会话" : run.status === "waiting" ? "等待确认" : run.status === "running" ? "处理中" : "知识库与工单";

  return (
    <div className="workbench">
      {sessionsOpen || detailsOpen ? <button type="button" className="sidebar-backdrop" aria-label="关闭侧栏" onClick={() => { setSessionsOpen(false); setDetailsOpen(false); }} /> : null}
      <SessionList sessions={sessions} activeId={activeId} disabled={locked} open={sessionsOpen} onClose={() => setSessionsOpen(false)} onSelect={(id) => void selectSession(id)} onCreate={newSession} />

      <main className="workbench-chat">
        <header className="chat-header">
          <button type="button" className="session-toggle icon-button" aria-label="展开会话列表" aria-controls="session-sidebar" aria-expanded={sessionsOpen} onClick={() => { setSessionsOpen(true); setDetailsOpen(false); }}><PanelLeft size={17} /></button>
          <div className="min-w-0"><h1 className="truncate text-sm font-medium">{sessions.find((session) => session.id === activeId)?.title ?? "新会话"}</h1><p className="mt-0.5 text-[11px] text-muted">{statusLabel}</p></div>
          <button type="button" className="details-toggle icon-button ml-auto" aria-label="展开执行详情" aria-controls="execution-sidebar" aria-expanded={detailsOpen} onClick={() => { setDetailsOpen(true); setSessionsOpen(false); }}><PanelRight size={17} /></button>
        </header>

        <div ref={scrollRef} className="conversation-scroll" onScroll={(event) => { const el = event.currentTarget; followReply.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120; }}>
          <div className={"conversation-content " + (!hasConversation ? "is-empty" : "")}>
            {loading ? <div role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-muted"><Loader2 size={16} className="animate-spin" />正在加载会话…</div> : null}
            {!loading && !hasConversation ? (
              <section className="chat-welcome">
                <div className="welcome-mark"><Terminal size={23} /></div>
                <h2>从你的资料开始</h2>
                <p>查阅处理规范，整理参考资料，<br className="sm:hidden" />把需要跟进的问题交给工单。</p>
                <button type="button" className="welcome-ingest" onClick={() => { setDetailsOpen(true); const form = document.querySelector<HTMLDetailsElement>(".workbench details.document-ingest"); if (form) { form.open = true; requestAnimationFrame(() => form.querySelector<HTMLInputElement>("input")?.focus()); } }}><BookOpen size={14} />先入库参考文档</button>
                <div className="query-suggestions">
                  {QUERY_SUGGESTIONS.map(({ icon: Icon, title, description, query }) => (
                    <button key={title} type="button" onClick={() => { setDraft(query); document.querySelector<HTMLTextAreaElement>(".chat-input")?.focus(); }} className="query-suggestion">
                      <Icon size={17} /><span><strong>{title}</strong><span>{description}</span></span>
                    </button>
                  ))}
                </div>
                <p className="welcome-note">文档问答需要先入库资料。资料不足时，应补充信息后再判断原因。</p>
              </section>
            ) : null}

            {history.map((record) => <ConversationTurn key={record.id} query={record.query ?? "历史问题"} answer={record.answer ?? ""} citations={record.citations ?? []} status={record.status === "failed" ? "error" : "done"} onInspect={() => inspect(record)} onCitation={(id) => inspect(record, id)} />)}

            {run.query ? (
              <ConversationTurn query={run.query} answer={run.answer} citations={run.citations} status={run.status} plan={run.plan} steps={run.steps} onInspect={() => inspect(null)} onCitation={(id) => inspect(null, id)}>
                {run.status === "waiting" && run.hitl ? <ApprovalCard key={run.runId + ":" + run.hitl.tool} tool={run.hitl.tool} args={run.hitl.args} onResolve={run.approve} /> : null}
                {run.status === "waiting" && !run.hitl ? <p role="status" className="mt-4 text-xs text-muted">正在恢复待确认的操作内容…</p> : null}
                {run.error ? <div role="alert" className="chat-error"><AlertCircle size={15} className="shrink-0" /><span>{run.error}</span></div> : null}
              </ConversationTurn>
            ) : null}
            {pageError ? <div role="alert" className="chat-error"><AlertCircle size={15} className="shrink-0" /><span>{pageError}</span></div> : null}
          </div>
        </div>

        <div className="composer-dock">
          <Composer value={draft} onChange={setDraft} running={run.status === "running"} waiting={run.status === "waiting"} disabled={loading || submitting} onSubmit={(query) => void submit(query)} onStop={() => void run.stop()} />
          <p className="composer-note">每次提问独立执行，请补充必要背景。关键结论请核对引用原文。</p>
        </div>
      </main>

      <aside id="execution-sidebar" aria-label="执行详情" className={"workbench-inspector " + (detailsOpen ? "is-open" : "")}>
        <div className="inspector-heading"><h2 className="text-sm font-medium">执行详情</h2><button type="button" className="inspector-close icon-button" aria-label="关闭执行详情" onClick={() => setDetailsOpen(false)}><X size={16} /></button></div>
        <div className="inspector-scroll">
          {sourceRecord ? <div className="inspected-record"><span>历史运行</span><p>{sourceRecord.query}</p><button type="button" onClick={() => inspect(null)}>返回当前运行</button></div> : null}
          {!sourceRecord ? <Timeline steps={run.steps} totalMs={run.totalMs} /> : null}
          <CitationPanel citations={citations} activeChunkId={hoveredChunk} selectedId={selectedCitation} onHover={setHoveredChunk} onSelect={setSelectedCitation} retrieval={retrieval} />
          {toolResults.length ? <section className="inspector-tools"><h3>工具结果</h3>{toolResults.map((item, index) => <ToolCard key={item.name + "-" + index} item={item} index={index} />)}</section> : null}
          <DocumentIngest />
          <details className="data-boundary"><summary>当前数据范围</summary><p>知识库来自你入库的文档；来源链接用于溯源，不会自动抓取网页。代码搜索仅覆盖本项目源码，指标查询使用演示样例，尚未接入业务监控。工单经确认后保存到本工作台。</p></details>
          {!sourceRecord ? <CostBar steps={run.steps} totalMs={run.totalMs} /> : null}
        </div>
      </aside>
    </div>
  );
}
