"use client";

import Link from "next/link";
import { KeyRound, LoaderCircle } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { authRequest, notifyAuthChanged } from "@/lib/auth";

type Mode = "login" | "register" | "verify-email" | "forgot-password" | "reset-password";
const TITLES: Record<Mode, string> = {
  login: "登录 AgentOps", register: "创建账号", "verify-email": "验证邮箱",
  "forgot-password": "找回密码", "reset-password": "设置新密码",
};
const DESCRIPTIONS: Record<Mode, string> = {
  login: "登录后开始排查工单，查看属于你的执行记录。",
  register: "注册后请验证邮箱，再进入工作台。",
  "verify-email": "确认验证邮箱后，即可登录工作台。",
  "forgot-password": "我们会向已验证的账号邮箱发送密码重置链接。",
  "reset-password": "密码更新后，所有已登录会话将失效。",
};

export default function AccountForm({ mode }: { mode: Mode }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [completed, setCompleted] = useState(false);
  const tokenLoaded = useRef(false);
  const needsToken = mode === "verify-email" || mode === "reset-password";
  const needsEmail = mode === "login" || mode === "register" || mode === "forgot-password";
  const needsPassword = mode === "login" || mode === "register" || mode === "reset-password";
  const newPassword = mode === "register" || mode === "reset-password";

  useEffect(() => {
    if (!needsToken || tokenLoaded.current) return;
    tokenLoaded.current = true;
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (value) setToken(value);
    else setError("链接缺少验证信息，请重新申请邮件。");
    window.history.replaceState(null, "", window.location.pathname);
  }, [needsToken]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setMessage("");
    if (newPassword && password !== confirmation) {
      setError("两次输入的密码不一致");
      return;
    }
    setBusy(true);
    try {
      const payload: Record<string, string> = {};
      if (needsEmail) payload.email = email;
      if (needsPassword) payload.password = password;
      if (needsToken) payload.token = token;
      if (mode === "register") payload.display_name = name;
      const data = await authRequest(mode, payload);
      setPassword("");
      setConfirmation("");
      if (mode === "login") {
        notifyAuthChanged();
        window.location.replace("/");
        return;
      }
      setMessage(data.message ?? "操作成功");
      if (needsToken) {
        setToken("");
        setCompleted(true);
      }
      if (mode === "reset-password") notifyAuthChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法连接账号服务");
    } finally { setBusy(false); }
  };

  const resend = async () => {
    if (!email) { setError("请先填写邮箱"); return; }
    setBusy(true);
    setError("");
    try {
      const data = await authRequest("resend-verification", { email });
      setMessage(data.message ?? "请检查收件箱");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "发送失败");
    } finally { setBusy(false); }
  };

  const inputClass = "mt-2 w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-white outline-none focus:border-brand-indigo";
  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-10">
      <form onSubmit={submit} className="glass w-full space-y-5 p-6">
        <div>
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-gradient text-ink-900"><KeyRound size={18} /></div>
          <h1 className="heading text-2xl">{TITLES[mode]}</h1>
          <p className="mt-2 text-sm text-muted">{DESCRIPTIONS[mode]}</p>
        </div>
        {mode === "register" ? (
          <label className="block text-sm text-muted">昵称
            <input name="display_name" autoComplete="nickname" className={inputClass} required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
        ) : null}
        {needsEmail ? (
          <label className="block text-sm text-muted">邮箱
            <input name="email" type="email" autoComplete="email" className={inputClass} required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
        ) : null}
        {needsPassword && !completed ? (
          <label className="block text-sm text-muted">{newPassword ? "新密码（至少 12 位）" : "密码"}
            <input name="password" type="password" autoComplete={newPassword ? "new-password" : "current-password"} className={inputClass} required minLength={newPassword ? 12 : 1} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
        ) : null}
        {newPassword && !completed ? (
          <label className="block text-sm text-muted">确认密码
            <input name="confirmation" type="password" autoComplete="new-password" className={inputClass} required maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
          </label>
        ) : null}
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
        {message ? <p role="status" className="text-sm text-success">{message}</p> : null}
        {!completed ? (
          <button type="submit" disabled={busy || (needsToken && !token)} className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-indigo px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">
            {busy ? <LoaderCircle size={16} className="animate-spin" /> : null}
            {busy ? "处理中..." : mode === "login" ? "登录" : mode === "register" ? "注册并发送验证邮件" : mode === "verify-email" ? "确认验证邮箱" : mode === "forgot-password" ? "发送重置邮件" : "更新密码"}
          </button>
        ) : null}
        {mode === "login" || mode === "register" ? <button type="button" disabled={busy} onClick={resend} className="text-sm text-brand-cyan">重新发送验证邮件</button> : null}
        <div className="flex flex-wrap gap-4 text-sm text-muted">
          {mode !== "login" ? <Link href="/login" className="hover:text-white">返回登录</Link> : <Link href="/register" className="hover:text-white">创建账号</Link>}
          {mode === "login" || mode === "reset-password" ? <Link href="/forgot-password" className="hover:text-white">忘记密码</Link> : null}
          {mode === "verify-email" && !token && !completed ? <Link href="/login" className="hover:text-white">重发验证邮件</Link> : null}
        </div>
      </form>
    </main>
  );
}
