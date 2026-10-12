export type RegistrationCaptcha = {
  captcha_id: string;
  image_data_url: string;
  expires_at: string;
};

export async function authRequest<T = { message?: string; detail?: unknown }>(action: string, payload: Record<string, string> = {}): Promise<T> {
  const response = await fetch(`/api/auth/${action}`, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-AgentOps-CSRF": "1" },
    body: JSON.stringify(payload),
  });
  const data = await response.json() as { message?: string; detail?: unknown };
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "输入内容无效，请检查后重试");
  }
  return data as T;
}

export async function requestRegistrationCaptcha(): Promise<RegistrationCaptcha> {
  const data = await authRequest<unknown>("captcha");
  if (!data || typeof data !== "object") throw new Error("验证码服务响应异常，请重试");
  const captcha = data as Partial<RegistrationCaptcha>;
  if (typeof captcha.captcha_id !== "string"
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(captcha.captcha_id)
    || typeof captcha.image_data_url !== "string"
    || !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(captcha.image_data_url)
    || typeof captcha.expires_at !== "string"
    || !/^\d{4}-\d{2}-\d{2}T/.test(captcha.expires_at)
    || !Number.isFinite(Date.parse(captcha.expires_at))) {
    throw new Error("验证码服务响应异常，请重试");
  }
  return captcha as RegistrationCaptcha;
}

export function notifyAuthChanged(): void {
  try {
    localStorage.setItem("agentops_auth_changed", String(Date.now()));
  } catch { /* Storage may be disabled; the current tab still navigates after auth changes. */ }
}

export function loginRequired(): void {
  if (typeof window !== "undefined") window.location.replace("/login");
}
