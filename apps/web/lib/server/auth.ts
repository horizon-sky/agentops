import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import type { AuthUser } from "@/lib/types";
import { jsonError, limitedBody, mutationAllowed, upstreamHeaders, upstreamUrl } from "./backend";

export const COOKIE_NAME = "agentops_session";
export const LEGACY_COOKIE_NAME = "agentops_auth";

export async function sessionToken(): Promise<string | undefined> {
  return (await cookies()).get(COOKIE_NAME)?.value;
}

export async function currentUser(): Promise<AuthUser | null> {
  const token = await sessionToken();
  if (!token) return null;
  const response = await fetch(upstreamUrl("/auth/session"), {
    headers: upstreamHeaders(token), cache: "no-store",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("authentication service unavailable");
  return ((await response.json()) as { user: AuthUser }).user;
}

const ACTIONS = new Set([
  "register", "login", "logout", "verify-email", "resend-verification",
  "forgot-password", "reset-password",
]);

export async function handleAuth(request: Request, action: string): Promise<NextResponse> {
  if (!ACTIONS.has(action)) return jsonError("接口不存在", 404);
  if (!mutationAllowed(request)) return jsonError("请求来源无效", 403);
  const body = await limitedBody(request, 8192);
  if (!body) return jsonError("请求内容过大", 413);
  let response: Response;
  try {
    response = await fetch(upstreamUrl(`/auth/${action}`), {
      method: "POST", headers: upstreamHeaders(await sessionToken(), request),
      body, cache: "no-store", redirect: "manual",
    });
  } catch {
    return jsonError("无法连接账号服务，请稍后重试", 503);
  }
  let data: Record<string, unknown>;
  try {
    data = await response.json() as Record<string, unknown>;
  } catch {
    return jsonError("账号服务响应异常", 502);
  }
  let token: string | undefined;
  let ttl = 0;
  if (action === "login" && response.ok) {
    token = typeof data.token === "string" ? data.token : undefined;
    ttl = Number(data.expires_in);
    if (!token || !Number.isFinite(ttl) || ttl <= 0) return jsonError("账号服务响应异常", 502);
    delete data.token;
    delete data.expires_in;
  }
  const result = NextResponse.json(data, {
    status: action === "logout" && response.status === 401 ? 200 : response.status,
    headers: { "Cache-Control": "no-store" },
  });
  for (const name of ["retry-after", "x-auth-reason"]) {
    const value = response.headers.get(name);
    if (value) result.headers.set(name, value);
  }
  if (token) {
    result.cookies.set(COOKIE_NAME, token, {
      httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax",
      path: "/", maxAge: Math.min(ttl, 86400),
    });
    result.cookies.delete(LEGACY_COOKIE_NAME);
  }
  if ((action === "logout" && (response.ok || response.status === 401))
    || (action === "reset-password" && response.ok)) {
    result.cookies.delete(COOKIE_NAME);
    result.cookies.delete(LEGACY_COOKIE_NAME);
  }
  return result;
}
