"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { archiveTicket, listTickets, updateTicket } from "@/lib/api";
import type { Ticket, TicketPage } from "@/lib/types";

const STATUS: Record<Ticket["status"], string> = {
  created: "待处理", in_progress: "处理中", resolved: "已解决", closed: "已关闭",
};
const FIELD = "mt-1 w-full rounded-lg border border-white/15 bg-ink-900 px-3 py-2 text-sm text-white focus:border-brand-indigo focus:outline-none";
const BUTTON = "rounded-lg border border-white/15 px-3 py-2 text-sm text-white hover:bg-white/5 disabled:opacity-40";

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
    <section className="glass p-4 sm:p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div><h1 className="heading">工单总览</h1><p className="mt-2 text-sm text-muted">管理审批后创建的工单与处理进度。</p></div>
        <button className={BUTTON} onClick={() => void load()} disabled={loading}>刷新</button>
      </div>
      {error ? <div role="alert" className="py-8 text-danger">加载失败：{error} <button className={BUTTON} onClick={() => void load()}>重试</button></div> : loading ? <p role="status" className="py-12 text-center text-muted">正在加载工单…</p> : !data?.items.length ? (
        <div className="py-12 text-center"><p className="text-white">暂无工单</p><p className="mt-2 text-sm text-muted">在工作台请求创建工单，确认审批后会显示在这里。</p><Link href="/" className="mt-4 inline-block text-brand-cyan">前往工作台</Link></div>
      ) : <>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/15 text-muted"><tr>{["工单编号", "标题", "优先级", "业务状态", "创建时间", "操作"].map((name) => <th key={name} scope="col" className="whitespace-nowrap px-3 py-3 font-normal">{name}</th>)}</tr></thead>
            <tbody>{data.items.map((ticket) => <tr key={ticket.id} className="border-b border-white/5 hover:bg-white/[0.03]">
              <td className="px-3 py-4"><span className="block max-w-48 truncate font-mono text-xs text-brand-cyan" title={ticket.ticket_id}>{ticket.ticket_id}</span></td>
              <td className="px-3 py-4"><span className="block min-w-40 max-w-sm break-words">{ticket.title}</span></td>
              <td className={`px-3 py-4 ${ticket.severity === "P0" ? "text-danger" : ticket.severity === "P1" ? "text-warning" : "text-muted"}`}>{ticket.severity}</td>
              <td className="whitespace-nowrap px-3 py-4">{STATUS[ticket.status]}</td>
              <td className="whitespace-nowrap px-3 py-4 text-xs text-muted">{new Date(ticket.created_at).toLocaleString("zh-CN")}</td>
              <td className="whitespace-nowrap px-3 py-4"><button className="mr-4 text-brand-cyan hover:underline" onClick={() => { setEditing({ ...ticket }); setActionError(""); }}>编辑</button><button className="text-danger hover:underline" onClick={() => { setDeleting(ticket); setActionError(""); }}>删除</button></td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="mt-5 flex items-center justify-between gap-3 text-sm text-muted"><span>共 {data.total} 条 · 第 {page} / {Math.max(1, Math.ceil(data.total / 20))} 页</span><div className="flex gap-2"><button className={BUTTON} disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button><button className={BUTTON} disabled={page * 20 >= data.total} onClick={() => setPage(page + 1)}>下一页</button></div></div>
      </>}

      {editing || deleting ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
        <div role="dialog" aria-modal="true" aria-labelledby="ticket-dialog-title" className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-white/15 bg-ink-900 p-6">
          <h2 id="ticket-dialog-title" className="subheading">{editing ? "编辑工单" : "删除工单"}</h2>
          <p className="mt-2 break-all font-mono text-xs text-muted">{(editing ?? deleting)?.ticket_id}</p>
          {actionError ? <p role="alert" className="mt-3 text-sm text-danger">{actionError}</p> : null}
          {editing ? <form onSubmit={save} className="mt-5 space-y-4">
            <label className="block text-sm text-muted">标题<input autoFocus required maxLength={300} value={editing.title} disabled={busy} onChange={(e) => setEditing({ ...editing, title: e.target.value })} className={FIELD} /></label>
            <label className="block text-sm text-muted">描述<textarea rows={5} maxLength={20000} value={editing.detail} disabled={busy} onChange={(e) => setEditing({ ...editing, detail: e.target.value })} className={FIELD} /></label>
            <div className="grid grid-cols-2 gap-4"><label className="text-sm text-muted">优先级<select className={FIELD} value={editing.severity} disabled={busy} onChange={(e) => setEditing({ ...editing, severity: e.target.value as Ticket["severity"] })}>{["P0", "P1", "P2", "P3"].map((s) => <option key={s}>{s}</option>)}</select></label><label className="text-sm text-muted">业务状态<select className={FIELD} value={editing.status} disabled={busy} onChange={(e) => setEditing({ ...editing, status: e.target.value as Ticket["status"] })}>{Object.entries(STATUS).map(([s, name]) => <option key={s} value={s}>{name}</option>)}</select></label></div>
            <div className="flex justify-end gap-2"><button type="button" disabled={busy} className={BUTTON} onClick={() => setEditing(null)}>取消</button><button disabled={busy || !editing.title.trim()} className={`${BUTTON} bg-brand-indigo/30`}>{busy ? "保存中…" : "保存修改"}</button></div>
          </form> : <><p className="my-5 text-sm text-muted">确认删除「{deleting?.title}」？删除后将从总览隐藏，历史执行记录仍会保留。</p><div className="flex justify-end gap-2"><button autoFocus disabled={busy} className={BUTTON} onClick={() => setDeleting(null)}>取消</button><button disabled={busy} className={`${BUTTON} text-danger`} onClick={() => void remove()}>{busy ? "删除中…" : "确认删除"}</button></div></>}
        </div>
      </div> : null}
    </section>
  );
}
