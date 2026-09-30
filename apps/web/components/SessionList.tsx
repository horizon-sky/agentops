"use client";

import { MessageSquarePlus, MessagesSquare } from "lucide-react";
import type { Session } from "@/lib/types";

export default function SessionList({
  sessions,
  activeId,
  onSelect,
  onCreate,
}: {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <aside className="glass flex w-64 shrink-0 flex-col p-3">
      <div className="mb-3 flex items-center gap-2">
        <MessagesSquare size={14} className="text-brand-cyan" />
        <span className="subheading">会话</span>
        <button
          onClick={onCreate}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-muted transition hover:border-brand-indigo hover:text-white"
        >
          <MessageSquarePlus size={14} />
        </button>
      </div>

      <div className="flex-1 space-y-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <p className="px-1 text-xs text-muted">还没有会话，点击右上角新建。</p>
        ) : (
          sessions.map((session) => {
            const active = session.id === activeId;
            return (
              <button
                key={session.id}
                onClick={() => onSelect(session.id)}
                className={`w-full rounded-xl border px-3 py-2 text-left text-xs transition ${
                  active
                    ? "border-brand-indigo/60 bg-brand-indigo/10 text-white"
                    : "border-transparent text-muted hover:border-white/10 hover:bg-white/5 hover:text-white"
                }`}
              >
                <div className="truncate">{session.title}</div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-muted/70">
                  {session.id.slice(0, 8)}
                </div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
