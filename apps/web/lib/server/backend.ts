import { NextResponse } from "next/server";

const proxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export function upstreamUrl(path: string): URL {
  return new URL(path, proxyTarget.endsWith("/") ? proxyTarget : `${proxyTarget}/`);
}

export function upstreamHeaders(token?: string, request?: Request): Headers {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const gateway = process.env.API_TOKEN?.trim();
  if (gateway) headers.set("X-API-Token", gateway);
  if (request) {
    // Vercel overwrites x-forwarded-for; never copy a caller's identity headers.
    const address = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
    headers.set("X-AgentOps-Client-IP", address);
  }
  return headers;
}

export function mutationAllowed(request: Request): boolean {
  return request.headers.get("origin") === new URL(request.url).origin
    && request.headers.get("x-agentops-csrf") === "1";
}

export async function limitedBody(request: Request, limit: number): Promise<ArrayBuffer | null> {
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer as ArrayBuffer;
}

export function jsonError(detail: string, status: number): NextResponse {
  return NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}
