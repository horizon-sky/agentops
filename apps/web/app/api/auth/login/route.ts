import { NextResponse } from "next/server";
import {
  COOKIE_NAME,
  SESSION_TTL_SECONDS,
  authEnabled,
  createSessionValue,
  tokenMatches,
} from "@/lib/server/auth";

export async function POST(request: Request) {
  if (!authEnabled()) return NextResponse.json({ authenticated: true, enabled: false });

  let token = "";
  try {
    const body = (await request.json()) as { token?: unknown };
    token = typeof body.token === "string" ? body.token : "";
  } catch {
    return NextResponse.json({ detail: "invalid request" }, { status: 400 });
  }

  if (!tokenMatches(token)) {
    return NextResponse.json({ detail: "invalid token" }, { status: 401 });
  }

  const response = NextResponse.json({ authenticated: true, enabled: true });
  response.cookies.set(COOKIE_NAME, createSessionValue(), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
  return response;
}
