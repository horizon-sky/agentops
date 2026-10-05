"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-6">
      <div className="glass w-full space-y-4 p-6">
        <h1 className="heading text-xl">暂时无法加载工作台</h1>
        <p className="text-sm text-muted">请检查账号服务连接，稍后重试。</p>
        <button className="rounded-lg bg-brand-indigo px-4 py-2 text-white" onClick={reset}>重试</button>
      </div>
    </main>
  );
}
