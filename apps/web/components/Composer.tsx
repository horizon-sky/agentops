"use client";

import { CornerDownLeft, Square } from "lucide-react";
import { useState } from "react";

export default function Composer({
  running,
  onSubmit,
  onStop,
}: {
  running: boolean;
  onSubmit: (query: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState("");

  const submit = () => {
    const query = value.trim();
    if (!query || running) return;
    onSubmit(query);
    setValue("");
  };

  return (
    <div className="glass flex items-center gap-3 p-3">
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="描述一个研发问题，例如：订单服务昨晚 5xx 报警，帮我定位并建单"
        className="min-w-0 flex-1 bg-transparent px-2 text-sm text-white outline-none placeholder:text-muted/70"
      />

      {running ? (
        <button
          onClick={onStop}
          className="inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-3 py-2 text-xs text-danger transition hover:bg-danger/10"
        >
          <Square size={12} />
          中断
        </button>
      ) : null}

      <button
        onClick={submit}
        disabled={running || value.trim().length === 0}
        className="inline-flex items-center gap-1.5 rounded-lg bg-brand-gradient px-4 py-2 text-xs font-medium text-ink-900 transition enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <CornerDownLeft size={13} />
        执行
      </button>
    </div>
  );
}
