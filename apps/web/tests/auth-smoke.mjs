// Production Next.js HTTP checks with a local mock backend; no real emails or accounts.
// Run after pnpm build: node tests/auth-smoke.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";

await (await import("./auth.test.cjs")).default;

const user = { id: "test-user", email: "test@example.com", display_name: "Test", role: "member" };
const token = "mock-personal-token";
const gateway = "mock-gateway-secret";
const calls = [];
let active = true;
let unavailable = false;
let captchaFailure = false;
const captcha = {
  captcha_id: "62e4e40a-29d1-4d1d-9a25-66dd8a48d205",
  image_data_url: "data:image/png;base64,iVBORw0KGgo=",
  expires_at: "2099-01-01T00:00:00Z",
};
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
  } else if (req.url === "/auth/captcha") {
    if (captchaFailure) res.writeHead(503).end(JSON.stringify({ detail: "Captcha unavailable" }));
    else res.end(JSON.stringify(captcha));
  } else if (req.url === "/auth/register") {
    const payload = JSON.parse(body);
    if (payload.captcha_answer === "wrong") res.writeHead(400).end(JSON.stringify({ detail: "验证码无效或已过期" }));
    else if (payload.email === "duplicate@example.com") res.writeHead(409).end(JSON.stringify({ detail: "该邮箱已注册" }));
    else res.writeHead(201).end(JSON.stringify({ message: "注册成功，请登录" }));
  } else if (req.url === "/auth/resend-verification") {
    res.writeHead(410).end(JSON.stringify({ detail: "邮箱验证已停用" }));
  } else if (req.url === "/auth/forgot-password") {
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
    if (user.role !== "admin") res.writeHead(403).end(JSON.stringify({ detail: "admin required" }));
    else res.end(JSON.stringify({ status: "empty", metrics: {}, report_path: "" }));
  } else if (req.url === "/sessions") {
    res.end(JSON.stringify([]));
  } else if (req.url === "/tickets?page=2") {
    res.end(JSON.stringify({ items: [], total: 0, page: 2, page_size: 20 }));
  } else if (req.url === "/tickets/mock-ticket" && ["PATCH", "DELETE"].includes(req.method)) {
    res.end(JSON.stringify({ id: "mock-ticket" }));
  } else if (req.url === "/documents/mock-document/chunks/mock-chunk") {
    res.end(JSON.stringify({ content: "Original source" }));
  } else if (req.url === "/ingest" && req.method === "POST") {
    res.writeHead(201).end(JSON.stringify({ document_id: "mock-document", chunks: 1, embedded: 0 }));
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
  for (const path of ["/", "/tickets", "/traces", "/evals"]) {
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
  const beforeCaptchaRejections = calls.length;
  for (const extra of [{ Origin: "https://evil.example" }, { "X-AgentOps-CSRF": "" }]) {
    const rejected = await post("captcha", {}, undefined, extra);
    assert.equal(rejected.status, 403, "Captcha issuance requires origin and CSRF checks");
    assert.equal(rejected.headers.get("cache-control"), "no-store");
  }
  assert.equal(calls.length, beforeCaptchaRejections, "Rejected captcha requests must not reach the backend");
  const issuedCaptcha = await post("captcha", {}, undefined, {
    Authorization: "Bearer attacker", "X-API-Token": "attacker",
  });
  assert.equal(issuedCaptcha.status, 200, "Unauthenticated visitors can obtain captcha");
  assert.deepEqual(await issuedCaptcha.json(), captcha);
  assert.equal(issuedCaptcha.headers.get("cache-control"), "no-store");
  assert.equal(issuedCaptcha.headers.getSetCookie().length, 0);
  assert.equal(calls.at(-1).headers.authorization, undefined);
  assert.equal(calls.at(-1).headers["x-api-token"], gateway);
  assert.deepEqual(JSON.parse(calls.at(-1).body), {});
  captchaFailure = true;
  const failedCaptcha = await post("captcha");
  assert.equal(failedCaptcha.status, 503);
  assert.deepEqual(await failedCaptcha.json(), { detail: "Captcha unavailable" });
  assert.equal(failedCaptcha.headers.get("cache-control"), "no-store");
  captchaFailure = false;
  const registration = {
    email: user.email, password: "mock-password", display_name: "Test",
    captcha_id: captcha.captcha_id, captcha_answer: "aB234",
  };
  for (const [payload, status, expected] of [
    [registration, 201, { message: "注册成功，请登录" }],
    [{ ...registration, captcha_answer: "wrong" }, 400, { detail: "验证码无效或已过期" }],
    [{ ...registration, email: "duplicate@example.com" }, 409, { detail: "该邮箱已注册" }],
  ]) {
    const response = await post("register", payload);
    assert.equal(response.status, status);
    assert.deepEqual(await response.json(), expected);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.getSetCookie().length, 0, "Registration must not log in");
    assert.deepEqual(JSON.parse(calls.at(-1).body), payload, "Captcha and account fields reach backend unchanged");
  }
  assert.equal((await post("verify-email", { token: "mail-token" })).status, 200);
  const retiredResend = await post("resend-verification", { email: user.email });
  assert.equal(retiredResend.status, 410);
  assert.deepEqual(await retiredResend.json(), { detail: "邮箱验证已停用" });
  assert.equal(retiredResend.headers.get("cache-control"), "no-store");
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
  assert.equal((await fetch(`${origin}/tickets`, { headers: { Cookie: cookie } })).status, 200);
  const tickets = await fetch(`${origin}/api/tickets?page=2`, { headers: { Cookie: cookie } });
  assert.equal(tickets.status, 200);
  assert.equal((await tickets.json()).page, 2);
  const preview = await fetch(`${origin}/api/documents/mock-document/chunks/mock-chunk`, {
    headers: { Cookie: cookie, Authorization: "Bearer attacker" },
  });
  assert.equal((await preview.json()).content, "Original source");
  assert.equal(calls.at(-1).headers.authorization, `Bearer ${token}`);
  for (const method of ["PATCH", "DELETE"]) {
    const rejectedCount = calls.length;
    assert.equal((await fetch(`${origin}/api/tickets/mock-ticket`, {
      method, headers: { Cookie: cookie, Origin: origin },
    })).status, 403);
    assert.equal(calls.length, rejectedCount);
    assert.equal((await fetch(`${origin}/api/tickets/mock-ticket`, {
      method, headers: { Cookie: cookie, Origin: origin, "X-AgentOps-CSRF": "1", "Content-Type": "application/json" },
      ...(method === "PATCH" ? { body: JSON.stringify({ title: "Edited" }) } : {}),
    })).status, 200);
    assert.equal(calls.at(-1).headers.authorization, `Bearer ${token}`);
  }
  assert.equal((await fetch(`${origin}/api/ingest`, {
    method: "POST", headers: { Cookie: cookie, Origin: origin, "X-AgentOps-CSRF": "1", "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Manual", source: "", content: "Original source" }),
  })).status, 201);
  assert.equal((await fetch(`${origin}/api/eval/report`, { headers: { Cookie: cookie } })).status, 403);
  const memberEval = await fetch(`${origin}/evals`, { headers: { Cookie: cookie } });
  assert.match(await memberEval.text(), /评测看板仅管理员可访问/);
  user.role = "admin";
  const adminEval = await fetch(`${origin}/evals`, { headers: { Cookie: cookie } });
  const adminHtml = await adminEval.text();
  assert.equal(adminEval.status, 200);
  assert.match(adminHtml, /href="\/evals"/);
  assert.match(adminHtml, /正在读取评测报告/);
  const emptyEval = await fetch(`${origin}/api/eval/report`, { headers: { Cookie: cookie } });
  assert.equal(emptyEval.status, 200);
  assert.equal((await emptyEval.json()).status, "empty");
  assert.equal(calls.at(-1).headers.authorization, `Bearer ${token}`);
  user.role = "member";
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
  console.log("PASS: protected pages, captcha issuance, registration status/body/errors/cache, email endpoints, CSRF, private cookies, ticket pagination/edit/archive, ingestion, source preview, identity and logout");
} finally {
  child.kill();
  if (child.exitCode === null && child.signalCode === null) {
    await once(child, "exit").catch(() => undefined);
  }
  backend.closeAllConnections();
  await new Promise((resolve) => backend.close(resolve));
}
