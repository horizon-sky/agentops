"use client";

import Link from "next/link";
import { Archive, ChevronLeft, ChevronRight, Pencil, RefreshCw, Save, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { archiveTicket, listTickets, updateTicket } from "@/lib/api";
import type { Ticket, TicketPage } from "@/lib/types";

const STATUS: Record<Ticket["status"], string> = {
  created: "待处理", in_progress: "处理中", resolved: "已解决", closed: "已关闭",
};
const STATUS_STYLE: Record<Ticket["status"], string> = {
  created: "ticket-status ticket-status-created",
  in_progress: "ticket-status ticket-status-progress",
  resolved: "ticket-status ticket-status-resolved",
  closed: "ticket-status ticket-status-closed",
};

export default function TicketOverview() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TicketPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Ticket | null>(null);
  const [deleting, setDeleting] = useState<Ticket | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await listTickets(page);
      if (page > 1 && result.items.length === 0) setPage(Math.max(1, Math.ceil(result.total / 20)));
      else setData(result);
    } catch (e) { setError(e instanceof Error ? e.message : "工单加载失败"); }
    finally { setLoading(false); }
  }, [page]);
  useEffect(() => { void load(); }, [load]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editing || busy) return;
    setBusy(true);
    setActionError("");
    try {
      const { title, detail, severity, status } = editing;
      await updateTicket(editing.id, { title: title.trim(), detail, severity, status });
      setEditing(null);
      await load();
    } catch (e) { setActionError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!deleting || busy) return;
    setBusy(true);
    setActionError("");
    try {
      await archiveTicket(deleting.id);
      setDeleting(null);
      await load();
    } catch (e) { setActionError(e instanceof Error ? e.message : "删除失败"); }
    finally { setBusy(false); }
  };

  return (
    <main className="ops-page tickets-page">
      <header className="ops-page-header">
        <div>
          <p className="ops-kicker">工作台 · 跟进队列</p>
          <h1>工单总览</h1>
          <p className="ops-page-description">管理已确认创建的事项，持续更新处理进度。</p>
        </div>
        <button className="ops-button ops-button-secondary" onClick={() => void load()} disabled={loading} title="刷新工单列表">
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />刷新
        </button>
      </header>
      <div className="ticket-summary" aria-label="工单统计">
        <div><span>全部工单</span><strong>{data?.total ?? "—"}</strong></div>
        <div><span>当前页</span><strong>{data?.items.length ?? "—"}</strong></div>
        <div><span>本页待处理</span><strong>{data?.items.filter((item) => item.status === "created" || item.status === "in_progress").length ?? "—"}</strong></div>
        <div><span>本页已完成</span><strong>{data?.items.filter((item) => item.status === "resolved" || item.status === "closed").length ?? "—"}</strong></div>
      </div>
      <section className="ops-panel ticket-panel">
      {error ? <div role="alert" className="ops-state ops-state-error"><p>加载工单失败</p><span>{error}</span><button className="ops-button ops-button-secondary" onClick={() => void load()}>重试</button></div> : loading ? <p role="status" className="ops-state">正在加载工单…</p> : !data?.items.length ? (
        <div className="ops-state"><p>暂无工单</p><span>在工作台确认创建后，工单会出现在这里。</span><Link href="/" className="ops-link">前往工作台</Link></div>
      ) : <>
        <div className="overflow-x-auto">
          <table className="ticket-table">
            <thead><tr>{["工单", "标题", "优先级", "状态", "创建时间", "操作"].map((name) => <th key={name} scope="col">{name}</th>)}</tr></thead>
            <tbody>{data.items.map((ticket) => <tr key={ticket.id}>
              <td><span className="ticket-id" title={ticket.ticket_id}>{ticket.ticket_id}</span></td>
              <td><span className="ticket-title">{ticket.title}</span><span className="ticket-detail">{ticket.detail}</span></td>
              <td><span className={`ticket-severity ticket-severity-${ticket.severity.toLowerCase()}`}>{ticket.severity}</span></td>
              <td><span className={STATUS_STYLE[ticket.status]}>{STATUS[ticket.status]}</span></td>
              <td className="ticket-date">{new Date(ticket.created_at).toLocaleString("zh-CN")}</td>
              <td><div className="ticket-actions"><button title="编辑工单" aria-label={`编辑 ${ticket.ticket_id}`} onClick={() => { setEditing({ ...ticket }); setActionError(""); }}><Pencil size={14} /></button><button className="is-danger" title="归档工单" aria-label={`归档 ${ticket.ticket_id}`} onClick={() => { setDeleting(ticket); setActionError(""); }}><Archive size={14} /></button></div></td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="ticket-pagination"><span>共 {data.total} 条 · 第 {page} / {Math.max(1, Math.ceil(data.total / 20))} 页</span><div><button title="上一页" aria-label="上一页" disabled={page === 1} onClick={() => setPage(page - 1)}><ChevronLeft size={16} /></button><button title="下一页" aria-label="下一页" disabled={page * 20 >= data.total} onClick={() => setPage(page + 1)}><ChevronRight size={16} /></button></div></div>
      </>}
      </section>

      {editing || deleting ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
        <div role="dialog" aria-modal="true" aria-labelledby="ticket-dialog-title" className="ticket-dialog">
          <div className="ticket-dialog-heading"><div><p className="ops-kicker">工单操作</p><h2 id="ticket-dialog-title">{editing ? "编辑工单" : "归档工单"}</h2></div><button title="关闭" aria-label="关闭" onClick={() => { setEditing(null); setDeleting(null); }}><X size={17} /></button></div>
          <p className="mt-2 break-all font-mono text-xs text-muted">{(editing ?? deleting)?.ticket_id}</p>
          {actionError ? <p role="alert" className="mt-3 text-sm text-danger">{actionError}</p> : null}
          {editing ? <form onSubmit={save} className="mt-5 space-y-4">
            <label className="ticket-field">标题<input autoFocus required maxLength={300} value={editing.title} disabled={busy} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></label>
            <label className="ticket-field">描述<textarea rows={5} maxLength={20000} value={editing.detail} disabled={busy} onChange={(e) => setEditing({ ...editing, detail: e.target.value })} /></label>
            <div className="grid grid-cols-2 gap-4"><label className="ticket-field">优先级<select value={editing.severity} disabled={busy} onChange={(e) => setEditing({ ...editing, severity: e.target.value as Ticket["severity"] })}>{["P0", "P1", "P2", "P3"].map((s) => <option key={s}>{s}</option>)}</select></label><label className="ticket-field">业务状态<select value={editing.status} disabled={busy} onChange={(e) => setEditing({ ...editing, status: e.target.value as Ticket["status"] })}>{Object.entries(STATUS).map(([s, name]) => <option key={s} value={s}>{name}</option>)}</select></label></div>
            <div className="ticket-dialog-actions"><button type="button" disabled={busy} className="ops-button ops-button-secondary" onClick={() => setEditing(null)}>取消</button><button disabled={busy || !editing.title.trim()} className="ops-button ops-button-primary"><Save size={14} />{busy ? "保存中…" : "保存修改"}</button></div>
          </form> : <p className="ticket-archive-copy">确认归档「{deleting?.title}」？归档后将从总览隐藏，历史执行记录仍会保留。</p>}
          {deleting ? <div className="ticket-dialog-actions"><button autoFocus disabled={busy} className="ops-button ops-button-secondary" onClick={() => setDeleting(null)}>取消</button><button disabled={busy} className="ops-button ops-button-danger" onClick={() => void remove()}><Archive size={14} />{busy ? "归档中…" : "确认归档"}</button></div> : null}
        </div>
      </div> : null}
    </main>
  );
}
