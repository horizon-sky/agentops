"use client";

import { MessageSquare, MessageSquarePlus, X } from "lucide-react";
import type { Session } from "@/lib/types";

export default function SessionList({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onClose,
  open,
  disabled,
}: {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onClose: () => void;
  open: boolean;
  disabled: boolean;
}) {
  return (
    <aside id="session-sidebar" aria-label="会话列表" className={`workbench-sessions ${open ? "is-open" : ""}`}>
      <div className="mb-5 flex items-center justify-between">
        <span className="text-sm font-medium">会话</span>
        <button type="button" onClick={onClose} aria-label="关闭会话列表" className="session-close icon-button"><X size={16} /></button>
      </div>
        <button
          type="button"
          onClick={onCreate}
          disabled={disabled}
          className="new-conversation"
        >
          <MessageSquarePlus size={14} />
          新建会话
        </button>
      <p className="mb-2 mt-6 px-2 text-[11px] text-muted">最近会话</p>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <p className="px-2 text-xs leading-6 text-muted">发送第一个问题后，<br />会话会显示在这里。</p>
        ) : (
          sessions.map((session) => {
            const active = session.id === activeId;
            return (
              <button
                key={session.id}
                type="button"
                onClick={() => onSelect(session.id)}
                disabled={disabled}
                aria-current={active ? "true" : undefined}
                className={`conversation-link ${active ? "is-active" : ""}`}
              >
                <MessageSquare size={14} className="shrink-0" />
                <span className="truncate">{session.title}</span>
              </button>
            );
          })
        )}
      </div>
      <div className="mt-4 border-t border-white/10 px-2 pt-4 text-[11px] leading-5 text-muted">资料仅用于当前账号。<br />工单在确认后创建。</div>
    </aside>
  );
}
