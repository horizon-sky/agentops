import { NextResponse } from "next/server";
import { authEnabled, isAuthenticated } from "@/lib/server/auth";

export async function GET() {
  return NextResponse.json({ enabled: authEnabled(), authenticated: await isAuthenticated() });
}
