import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME, sessionToken } from "@/lib/server/auth";
import { jsonError, limitedBody, mutationAllowed, upstreamHeaders, upstreamUrl } from "@/lib/server/backend";

async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname.replace(/^\/api/, "") || "/";
  if (!/^\/(sessions|runs|tickets|traces|ingest|eval|healthz)(\/|$)/.test(path)) {
    return jsonError("接口不存在", 404);
  }
  const method = request.method.toUpperCase();
  const mutation = method !== "GET" && method !== "HEAD";
  if (mutation && !mutationAllowed(request)) return jsonError("请求来源无效", 403);
  const token = await sessionToken();
  if (path !== "/healthz" && !token) return jsonError("authentication required", 401);
  const target = upstreamUrl(path);
  target.search = request.nextUrl.search;
  const headers = upstreamHeaders(token, request);
  headers.set("Accept", request.headers.get("accept") ?? "application/json");
  const body = mutation ? await limitedBody(request, 1_100_000) : undefined;
  if (body === null) return jsonError("请求内容过大", 413);
  let response: Response;
  try {
    response = await fetch(target, {
      method, headers, body, redirect: "manual", cache: "no-store", signal: request.signal,
    });
  } catch {
    return jsonError("upstream unavailable", 502);
  }
  const outgoing = new Headers({ "Cache-Control": "no-store" });
  for (const name of ["content-type", "retry-after", "x-accel-buffering"]) {
    const value = response.headers.get(name);
    if (value) outgoing.set(name, value);
  }
  const result = new NextResponse(response.body, { status: response.status, headers: outgoing });
  if (response.status === 401) result.cookies.delete(COOKIE_NAME);
  return result;
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
