export async function authRequest(action: string, payload: Record<string, string> = {}) {
  const response = await fetch(`/api/auth/${action}`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-AgentOps-CSRF": "1" },
    body: JSON.stringify(payload),
  });
  const data = await response.json() as { message?: string; detail?: unknown };
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "输入内容无效，请检查后重试");
  }
  return data;
}

export function notifyAuthChanged(): void {
  try {
    localStorage.setItem("agentops_auth_changed", String(Date.now()));
  } catch { /* Storage may be disabled; session checks still run on focus and a timer. */ }
}

export function loginRequired(): void {
  if (typeof window !== "undefined") window.location.replace("/login");
}
