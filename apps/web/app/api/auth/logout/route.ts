import { NextResponse } from "next/server";
import { COOKIE_NAME } from "@/lib/server/auth";

export async function POST() {
  const response = NextResponse.json({ authenticated: false });
  response.cookies.delete(COOKIE_NAME);
  return response;
}
