import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/server/auth";

const proxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname.replace(/^\/api/, "") || "/";
  const target = new URL(path, proxyTarget.endsWith("/") ? proxyTarget : `${proxyTarget}/`);
  target.search = request.nextUrl.search;

  if (path !== "/healthz" && !(await isAuthenticated())) {
    return NextResponse.json({ detail: "authentication required" }, { status: 401 });
  }

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  const apiToken = process.env.API_TOKEN?.trim();
  if (apiToken) headers.set("authorization", `Bearer ${apiToken}`);

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  let response: Response;
  try {
    response = await fetch(target, {
      method,
      headers,
      body,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "upstream unavailable" }, { status: 502 });
  }

  return new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
