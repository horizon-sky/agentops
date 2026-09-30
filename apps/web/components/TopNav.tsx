"use client";

import { Activity, Github, Radar } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const NAV = [
  { to: "/", label: "工作台" },
  { to: "/traces", label: "Trace 回放" },
  { to: "/evals", label: "评测看板" },
];

export default function TopNav() {
  const pathname = usePathname();
  const [modelTier, setModelTier] = useState("strong");

  return (
    <header className="fixed inset-x-0 top-0 z-30 border-b border-white/10 bg-ink-900/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-6 px-6">
        <div className="flex items-center gap-3">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-brand-gradient shadow-glow">
            <Radar size={18} className="text-ink-900" />
            <span className="absolute inset-0 rounded-xl border border-brand-cyan/40 animate-pulse-ring" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-wide text-white">AgentOps</div>
            <div className="text-[11px] text-muted">研发工单自动化 Agent</div>
          </div>
        </div>

        <nav className="flex items-center gap-1">
          {NAV.map((item) => {
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                href={item.to}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${
                  active
                    ? "bg-white/10 text-white shadow-glow"
                    : "text-muted hover:bg-white/5 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="pill">
            <Activity size={12} className="text-success" />
            在线
          </span>
          <label className="flex items-center gap-2 text-xs text-muted">
            模型档位
            <select
              value={modelTier}
              onChange={(event) => setModelTier(event.target.value)}
              className="rounded-lg border border-white/10 bg-ink-800 px-2 py-1 text-xs text-white outline-none focus:border-brand-indigo"
            >
              <option value="strong">strong · 规划与生成</option>
              <option value="cheap">cheap · 分类与改写</option>
            </select>
          </label>
          <a
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-muted transition hover:text-white"
          >
            <Github size={15} />
          </a>
        </div>
      </div>
    </header>
  );
}
