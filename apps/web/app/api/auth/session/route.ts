import { COOKIE_NAME, sessionToken } from "@/lib/server/auth";
import { jsonError, upstreamHeaders, upstreamUrl } from "@/lib/server/backend";
import { NextResponse } from "next/server";

export async function GET() {
  const token = await sessionToken();
  if (!token) return jsonError("authentication required", 401);
  try {
    const upstream = await fetch(upstreamUrl("/auth/session"), {
      headers: upstreamHeaders(token), cache: "no-store",
    });
    const result = NextResponse.json(await upstream.json(), {
      status: upstream.status, headers: { "Cache-Control": "no-store" },
    });
    if (upstream.status === 401) result.cookies.delete(COOKIE_NAME);
    return result;
  } catch {
    return jsonError("无法连接账号服务", 503);
  }
}
