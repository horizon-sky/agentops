// Production Next.js HTTP checks with a local mock backend; no real emails or accounts.
// Run after pnpm build: node tests/auth-smoke.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";

const user = { id: "test-user", email: "test@example.com", display_name: "Test", role: "member" };
const token = "mock-personal-token";
const gateway = "mock-gateway-secret";
const calls = [];
let active = true;
let unavailable = false;
const backend = createServer(async (req, res) => {
  let body = "";
  for await (const chunk of req) body += chunk;
  calls.push({ path: req.url, headers: req.headers, body });
  res.setHeader("Content-Type", "application/json");
  if (unavailable) {
    res.writeHead(503).end(JSON.stringify({ detail: "mock unavailable" }));
    return;
  }
  assert.equal(req.headers["x-api-token"], gateway);
  if (req.url === "/auth/login") {
    active = true;
    res.end(JSON.stringify({ user, token, expires_in: 3600 }));
  } else if (["/auth/register", "/auth/resend-verification", "/auth/forgot-password"].includes(req.url)) {
    res.writeHead(202).end(JSON.stringify({ message: "Check email" }));
  } else if (["/auth/verify-email", "/auth/reset-password"].includes(req.url)) {
    res.end(JSON.stringify({ message: "Confirmed" }));
  } else if (!active || req.headers.authorization !== `Bearer ${token}`) {
    res.writeHead(401).end(JSON.stringify({ detail: "expired" }));
  } else if (req.url === "/auth/session") {
    res.end(JSON.stringify({ user }));
  } else if (req.url === "/auth/logout") {
    active = false;
    res.end(JSON.stringify({ message: "Logged out" }));
  } else if (req.url === "/eval/report") {
    res.writeHead(403).end(JSON.stringify({ detail: "admin required" }));
  } else if (req.url === "/sessions") {
    res.end(JSON.stringify([]));
  } else {
    res.writeHead(404).end(JSON.stringify({ detail: "not found" }));
  }
});
backend.listen(0, "127.0.0.1");
await once(backend, "listening");
const reservation = createServer();
reservation.listen(0, "127.0.0.1");
await once(reservation, "listening");
const port = reservation.address().port;
await new Promise((resolve) => reservation.close(resolve));
const origin = `http://localhost:${port}`;
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", String(port)], {
  cwd: fileURLToPath(new URL("../", import.meta.url)),
  windowsHide: true,
  env: {
    ...process.env, NODE_ENV: "production", API_TOKEN: gateway,
    API_PROXY_TARGET: `http://127.0.0.1:${backend.address().port}`,
    NEXT_PUBLIC_API_BASE_URL: "/api",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
let output = "";
child.stdout.on("data", (data) => { output += data; });
child.stderr.on("data", (data) => { output += data; });
const post = (action, body = {}, cookie, extra = {}) => fetch(`${origin}/api/auth/${action}`, {
  method: "POST", redirect: "manual",
  headers: {
    Origin: origin, "Content-Type": "application/json", "X-AgentOps-CSRF": "1",
    ...(cookie ? { Cookie: cookie } : {}), ...extra,
  },
  body: JSON.stringify(body),
});
try {
  const deadline = Date.now() + 30000;
  while (true) {
    try {
      if ((await fetch(`${origin}/login`)).ok) break;
    } catch { /* Server startup. */ }
    if (child.exitCode !== null || Date.now() > deadline) throw new Error(`Next.js startup failed: ${output}`);
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  for (const path of ["/", "/traces", "/evals"]) {
    const response = await fetch(`${origin}${path}`, { redirect: "manual" });
    assert.equal(response.status, 307);
    assert.equal(response.headers.get("location"), "/login");
  }
  for (const path of ["/register", "/forgot-password", "/verify-email", "/reset-password"]) {
    assert.equal((await fetch(`${origin}${path}`)).status, 200);
  }
  assert.equal(calls.length, 0, "GET email pages must not consume tokens");
  assert.equal((await fetch(`${origin}/api/auth/session`)).status, 401);
  assert.equal((await fetch(`${origin}/api/sessions`)).status, 401);
  assert.equal((await post("login", {}, undefined, { Origin: "https://evil.example" })).status, 403);
  assert.equal((await post("login", {}, undefined, { "X-AgentOps-CSRF": "" })).status, 403);
  assert.equal(calls.length, 0, "Rejected requests must not reach the backend");
  assert.equal((await post("login", { padding: "a".repeat(9000) })).status, 413);
  assert.equal((await post("unknown-action")).status, 404);
  assert.equal((await post("register", { email: user.email })).status, 202);
  assert.equal((await post("verify-email", { token: "mail-token" })).status, 200);
  const login = await post("login", { email: user.email, password: "mock-password" });
  assert.equal(login.status, 200);
  const json = await login.text();
  assert.deepEqual(JSON.parse(json), { user });
  assert.ok(!json.includes(token) && !json.includes(gateway));
  assert.equal(login.headers.get("cache-control"), "no-store");
  const cookies = login.headers.getSetCookie();
  const sessionCookie = cookies.find((value) => value.startsWith("agentops_session="));
  for (const flag of [/HttpOnly/i, /Secure/i, /SameSite=Lax/i, /Max-Age=3600/i]) {
    assert.match(sessionCookie, flag);
  }
  const cookie = sessionCookie.split(";")[0];
  const session = await fetch(`${origin}/api/auth/session`, { headers: { Cookie: cookie } });
  assert.equal(session.status, 200);
  assert.deepEqual(await session.json(), { user });
  assert.equal((await fetch(`${origin}/`, { headers: { Cookie: cookie } })).status, 200);
  const sessions = await fetch(`${origin}/api/sessions`, {
    headers: { Cookie: cookie, Authorization: "Bearer attacker", "X-API-Token": "attacker" },
  });
  assert.equal(sessions.status, 200);
  assert.equal(calls.at(-1).headers.authorization, `Bearer ${token}`);
  assert.equal(calls.at(-1).headers["x-api-token"], gateway);
  assert.equal((await fetch(`${origin}/api/eval/report`, { headers: { Cookie: cookie } })).status, 403);
  unavailable = true;
  assert.equal((await fetch(`${origin}/api/auth/session`, { headers: { Cookie: cookie } })).status, 503);
  const failedLogout = await post("logout", {}, cookie);
  assert.equal(failedLogout.status, 503);
  assert.equal(failedLogout.headers.getSetCookie().length, 0, "Failed logout must remain retryable");
  unavailable = false;
  const reset = await post("reset-password", { token: "mail-token", password: "new-password" }, cookie);
  assert.ok(reset.headers.getSetCookie().some((value) => value.startsWith("agentops_session=;")));
  const logout = await post("logout", {}, cookie);
  assert.equal(logout.status, 200);
  assert.ok(logout.headers.getSetCookie().some((value) => value.startsWith("agentops_session=;")));
  const expired = await fetch(`${origin}/api/sessions`, { headers: { Cookie: cookie } });
  assert.equal(expired.status, 401);
  assert.ok(expired.headers.getSetCookie().some((value) => value.startsWith("agentops_session=;")));
  assert.equal((await post("logout", {}, cookie)).status, 200, "Expired logout must still clear cookies");
  console.log("PASS: protected pages, email endpoints, CSRF, body limit, private cookies, identity headers, expiry and logout");
} finally {
  child.kill();
  if (child.exitCode === null && child.signalCode === null) {
    await once(child, "exit").catch(() => undefined);
  }
  backend.closeAllConnections();
  await new Promise((resolve) => backend.close(resolve));
}
