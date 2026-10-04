import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

const COOKIE_NAME = "agentops_auth";
const SESSION_TTL_SECONDS = 8 * 60 * 60;

function configuredToken(): string {
  return process.env.API_TOKEN?.trim() ?? "";
}

function signature(value: string): string {
  return createHmac("sha256", configuredToken()).update(value).digest("base64url");
}

function equal(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

export function authEnabled(): boolean {
  return configuredToken().length > 0;
}

export function tokenMatches(candidate: string): boolean {
  const expected = configuredToken();
  return expected.length > 0 && equal(candidate, expected);
}

export function createSessionValue(now = Math.floor(Date.now() / 1000)): string {
  const issuedAt = String(now);
  return `${issuedAt}.${signature(issuedAt)}`;
}

export function isValidSessionValue(
  value: string | undefined,
  now = Math.floor(Date.now() / 1000),
): boolean {
  if (!authEnabled() || !value) return !authEnabled();
  const [issuedAt, digest] = value.split(".");
  const timestamp = Number(issuedAt);
  if (!Number.isInteger(timestamp) || timestamp > now) return false;
  if (now - timestamp > SESSION_TTL_SECONDS || !digest) return false;
  return equal(digest, signature(issuedAt));
}

export async function isAuthenticated(): Promise<boolean> {
  if (!authEnabled()) return true;
  const value = (await cookies()).get(COOKIE_NAME)?.value;
  return isValidSessionValue(value);
}

export { COOKIE_NAME, SESSION_TTL_SECONDS };
