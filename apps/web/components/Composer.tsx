"use client";

import { ArrowUp, Square } from "lucide-react";

export default function Composer({
  running,
  waiting,
  disabled,
  value,
  onChange,
  onSubmit,
  onStop,
}: {
  running: boolean;
  waiting: boolean;
  disabled: boolean;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (query: string) => void;
  onStop: () => void;
}) {
  const submit = () => {
    const query = value.trim();
    if (!query || running || waiting || disabled) return;
    onSubmit(query);
    onChange("");
  };

  return (
    <div className="chat-composer">
      <textarea
        aria-label="发送给 Agent 的问题"
        rows={3}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        disabled={waiting || disabled}
        placeholder={waiting ? "请先确认或拒绝上方操作，再发送新问题" : "询问已入库的资料，或描述需要跟进的工单…"}
        className="chat-input"
      />
      <div className="flex items-center justify-between gap-3 px-3 pb-3">
        <span className="text-[11px] text-muted">{waiting ? "操作暂停，等待你的确认" : "Enter 发送 · Shift + Enter 换行"}</span>
      {running ? (
        <button
          type="button"
          onClick={onStop}
          aria-label="停止生成"
          title="停止生成"
          className="chat-send"
        >
          <Square size={15} fill="currentColor" />
        </button>
      ) : <button
        type="button"
        onClick={submit}
        aria-label="发送问题"
        title="发送问题"
        disabled={waiting || disabled || value.trim().length === 0}
        className="chat-send"
      >
        <ArrowUp size={18} />
      </button>}
      </div>
    </div>
  );
}
