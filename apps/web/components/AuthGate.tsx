"use client";

import { KeyRound, LoaderCircle } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

type AuthState = { enabled: boolean; authenticated: boolean };

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadSession = async () => {
    const response = await fetch("/api/auth/session", { cache: "no-store" });
    if (!response.ok) throw new Error("session unavailable");
    setState((await response.json()) as AuthState);
  };

  useEffect(() => {
    loadSession().catch(() => setError("无法连接认证服务"));
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (!response.ok) {
        setError("令牌无效，请重试");
        return;
      }
      setToken("");
      await loadSession();
    } catch {
      setError("无法连接认证服务");
    } finally {
      setSubmitting(false);
    }
  };

  if (!state) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted">
        <LoaderCircle size={18} className="mr-2 animate-spin" />
        正在连接工作台
      </div>
    );
  }

  if (!state.enabled || state.authenticated) return <>{children}</>;

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-6">
      <form onSubmit={submit} className="glass w-full space-y-5 p-6">
        <div>
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-gradient text-ink-900">
            <KeyRound size={18} />
          </div>
          <h1 className="heading text-2xl">登录 AgentOps</h1>
          <p className="mt-2 text-sm text-muted">输入工作台访问令牌以继续。</p>
        </div>
        <label className="block text-sm text-muted">
          访问令牌
          <input
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="mt-2 w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-white outline-none focus:border-brand-indigo"
            required
          />
        </label>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-brand-indigo px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-indigo/80 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "验证中..." : "进入工作台"}
        </button>
      </form>
    </main>
  );
}
