"use client";

import { FileText, Pencil, Plus, RefreshCw, Save, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { deleteDocument, fetchDocument, ingestDocument, listDocuments, updateDocument } from "@/lib/api";
import type { KnowledgeDocument } from "@/lib/types";

type Editor = {
  id?: string;
  title: string;
  source: string;
  version: string;
  content: string;
};

const TEXT_FILE_TYPES = ".txt,.md,.markdown,.json,.csv,.log,.yaml,.yml";

function emptyEditor(): Editor {
  return { title: "", source: "", version: "v1", content: "" };
}

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setDocuments(await listDocuments());
    } catch (e) {
      setError(e instanceof Error ? e.message : "知识库加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const openCreate = () => {
    setActionError("");
    setEditor(emptyEditor());
  };

  const openEdit = async (document: KnowledgeDocument) => {
    setActionError("");
    setEditor({ id: document.id, title: document.title, source: document.source, version: document.version, content: "" });
    setBusy(true);
    try {
      const detail = await fetchDocument(document.id);
      setEditor({ id: detail.id, title: detail.title, source: detail.source, version: detail.version, content: detail.content });
    } catch (e) {
      setEditor(null);
      setError(e instanceof Error ? e.message : "文档加载失败");
    } finally {
      setBusy(false);
    }
  };

  const readFile = async (file: File) => {
    if (file.size > 1_000_000) throw new Error("文件不能超过 1 MB");
    const content = await file.text();
    setEditor((current) => current ? {
      ...current,
      title: current.title.trim() ? current.title : file.name.replace(/\.[^.]+$/, ""),
      source: current.source.trim() ? current.source : file.name,
      content,
    } : current);
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editor || busy) return;
    if (new TextEncoder().encode(editor.content).length > 1_000_000) {
      setActionError("正文不能超过 1 MB");
      return;
    }
    setBusy(true);
    setActionError("");
    try {
      const payload = { title: editor.title.trim(), source: editor.source.trim(), version: editor.version.trim() || "v1", content: editor.content };
      if (editor.id) await updateDocument(editor.id, payload);
      else await ingestDocument(payload);
      setEditor(null);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!deleting || busy) return;
    setBusy(true);
    setActionError("");
    try {
      await deleteDocument(deleting.id);
      setDeleting(null);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  const chooseFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try { await readFile(file); } catch (e) { setActionError(e instanceof Error ? e.message : "文件读取失败"); }
  };

  return (
    <main className="ops-page knowledge-page">
      <header className="ops-page-header">
        <div>
          <p className="ops-kicker">工作台 · 内容资产</p>
          <h1>知识库</h1>
          <p className="ops-page-description">浏览、更新和清理当前账号可检索的参考文档。</p>
        </div>
        <div className="flex gap-2">
          <button className="ops-button ops-button-secondary" onClick={() => void load()} disabled={loading} title="刷新知识库">
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />刷新
          </button>
          <button className="ops-button ops-button-primary" onClick={openCreate}><Plus size={15} />新增知识库</button>
        </div>
      </header>

      <section className="ops-panel ticket-panel">
        {error ? <div role="alert" className="ops-state ops-state-error"><p>加载知识库失败</p><span>{error}</span><button className="ops-button ops-button-secondary" onClick={() => void load()}>重试</button></div> : loading ? <p role="status" className="ops-state">正在加载知识库…</p> : !documents.length ? (
          <div className="ops-state"><FileText size={25} /><p>暂无知识库文档</p><span>上传 Markdown 或文本文件，快速建立当前账号的检索资料。</span><button className="ops-button ops-button-primary" onClick={openCreate}><Plus size={15} />新增文档</button></div>
        ) : <div className="overflow-x-auto">
          <table className="ticket-table"><thead><tr>{["文档", "来源", "版本", "片段", "向量化", "创建时间", "操作"].map((name) => <th key={name}>{name}</th>)}</tr></thead>
            <tbody>{documents.map((document) => <tr key={document.id}>
              <td><span className="ticket-title">{document.title}</span><span className="ticket-detail">{document.id}</span></td>
              <td className="ticket-detail">{document.source || "—"}</td>
              <td><span className="ticket-severity">{document.version}</span></td>
              <td className="ticket-date">{document.chunks}</td>
              <td className="ticket-date">{document.embedded}/{document.chunks}</td>
              <td className="ticket-date">{document.created_at ? new Date(document.created_at).toLocaleString("zh-CN") : "—"}</td>
              <td><div className="ticket-actions"><button title="编辑文档" aria-label={`编辑 ${document.title}`} onClick={() => void openEdit(document)}><Pencil size={14} /></button><button className="is-danger" title="删除文档" aria-label={`删除 ${document.title}`} onClick={() => { setDeleting(document); setActionError(""); }}><Trash2 size={14} /></button></div></td>
            </tr>)}</tbody>
          </table>
        </div>}
      </section>

      {editor || deleting ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
        <div role="dialog" aria-modal="true" aria-labelledby="knowledge-dialog-title" className="ticket-dialog">
          <div className="ticket-dialog-heading"><div><p className="ops-kicker">知识库操作</p><h2 id="knowledge-dialog-title">{editor ? (editor.id ? "编辑文档" : "新增文档") : "删除文档"}</h2></div><button title="关闭" aria-label="关闭" onClick={() => { setEditor(null); setDeleting(null); setActionError(""); }}><X size={17} /></button></div>
          {actionError ? <p role="alert" className="mt-3 text-sm text-danger">{actionError}</p> : null}
          {editor ? <form onSubmit={save} className="mt-5 space-y-4">
            <label className="ticket-field">标题<input autoFocus required maxLength={300} disabled={busy} value={editor.title} onChange={(e) => setEditor({ ...editor, title: e.target.value })} /></label>
            <div className="grid grid-cols-2 gap-4"><label className="ticket-field">来源（选填）<input maxLength={500} disabled={busy} value={editor.source} onChange={(e) => setEditor({ ...editor, source: e.target.value })} /></label><label className="ticket-field">版本<input maxLength={64} disabled={busy} value={editor.version} onChange={(e) => setEditor({ ...editor, version: e.target.value })} /></label></div>
            <div className="flex items-center justify-between gap-3"><span className="text-xs text-muted">支持 .txt、.md、.json、.csv 等文本文件，最大 1 MB</span><input ref={fileInput} type="file" accept={TEXT_FILE_TYPES} className="hidden" onChange={(e) => void chooseFile(e)} /><button type="button" className="ops-button ops-button-secondary" disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={14} />选择文件</button></div>
            <label className="ticket-field">正文<textarea required rows={12} disabled={busy} value={editor.content} onChange={(e) => setEditor({ ...editor, content: e.target.value })} /></label>
            <div className="ticket-dialog-actions"><button type="button" disabled={busy} className="ops-button ops-button-secondary" onClick={() => setEditor(null)}>取消</button><button disabled={busy || !editor.title.trim() || !editor.content.trim()} className="ops-button ops-button-primary"><Save size={14} />{busy ? "保存中…" : editor.id ? "保存更新" : "创建文档"}</button></div>
          </form> : <><p className="ticket-archive-copy">确认删除「{deleting?.title}」？删除后文档和已生成的检索片段都会移除。</p><div className="ticket-dialog-actions"><button autoFocus disabled={busy} className="ops-button ops-button-secondary" onClick={() => setDeleting(null)}>取消</button><button disabled={busy} className="ops-button ops-button-danger" onClick={() => void remove()}><Trash2 size={14} />{busy ? "删除中…" : "确认删除"}</button></div></>}
        </div>
      </div> : null}
    </main>
  );
}
