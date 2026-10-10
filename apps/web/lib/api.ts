import type {
  AgentEvent,
  HitlPayload,
  RunRef,
  Session,
  ToolResultPayload,
  TraceNode,
  RunSnapshot,
  Ticket,
  TicketPage,
  ChunkPreview,
} from "./types";
import { loginRequired } from "./auth";

export const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", "X-AgentOps-CSRF": "1", ...init?.headers },
  });
  if (!response.ok) {
    if (response.status === 401) loginRequired();
    const detail = await response.text();
    throw new Error(`${response.status} ${detail.slice(0, 200)}`);
  }
  return (await response.json()) as T;
}

export function createSession(title: string): Promise<Session> {
  return request<Session>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function listSessions(): Promise<Session[]> {
  return request<Session[]>("/sessions");
}

export function listTickets(page = 1): Promise<TicketPage> {
  return request(`/tickets?page=${page}`);
}

export function updateTicket(id: string, fields: Pick<Ticket, "title" | "detail" | "severity" | "status">): Promise<Ticket> {
  return request(`/tickets/${id}`, { method: "PATCH", body: JSON.stringify(fields) });
}

export function archiveTicket(id: string): Promise<{ ok: boolean }> {
  return request(`/tickets/${id}`, { method: "DELETE" });
}

export function listSessionRuns(sessionId: string): Promise<RunSnapshot[]> {
  return request<RunSnapshot[]>(`/sessions/${sessionId}/runs`);
}

export function createRun(sessionId: string, query: string): Promise<RunRef> {
  return request<RunRef>("/runs", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, query }),
  });
}

export function resumeRun(
  runId: string,
  ok: boolean,
  args?: Record<string, unknown>,
  approvalId?: string,
): Promise<{ ok: boolean; detail?: string }> {
  return request(`/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify({ ok, args, approval_id: approvalId }),
  });
}

export function abortRun(runId: string): Promise<{ ok: boolean }> {
  return request(`/runs/${runId}/abort`, { method: "POST" });
}

export function fetchTrace(runId: string): Promise<TraceNode[]> {
  return request<TraceNode[]>(`/traces/${runId}`);
}

export function fetchEvalReport(): Promise<{
  metrics: Record<string, number | string>;
  report_path: string;
}> {
  return request("/eval/report");
}

export function ingestDocument(payload: {
  title: string;
  source: string;
  content: string;
}): Promise<{ document_id: string; chunks: number; embedded: number }> {
  return request("/ingest", { method: "POST", body: JSON.stringify(payload) });
}

export function fetchChunk(documentId: string, citationId: string): Promise<ChunkPreview> {
  return request(`/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(citationId)}`);
}

/** 用 fetch + ReadableStream 消费 SSE，支持 AbortController 随时中断。 */
export async function streamRun(
  runId: string,
  onEvent: (event: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/runs/${runId}/stream`, {
    headers: { Accept: "text/event-stream" },
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    if (response.status === 401) loginRequired();
    throw new Error(`stream failed: ${response.status}`);
  }
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.replace("data: ", "")) as AgentEvent;
      if (event.type === "error" && event.payload?.code === "auth_expired") {
        await reader.cancel();
        loginRequired();
        return;
      }
      onEvent(event);
    }
  }
}

export function isToolResult(payload: unknown): payload is ToolResultPayload {
  return typeof payload === "object" && payload !== null && "name" in payload;
}

export function isHitl(payload: unknown): payload is HitlPayload {
  return typeof payload === "object" && payload !== null && "tool" in payload;
}
