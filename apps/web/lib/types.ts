export type EventType =
  | "plan"
  | "retrieve"
  | "tool_result"
  | "hitl_request"
  | "token"
  | "done"
  | "error"
  | "ping";

export type Stage = "plan" | "retrieve" | "tools" | "generate";

export interface AgentEvent {
  id: string;
  type: EventType;
  run_id: string;
  payload?: Record<string, unknown> | null;
  stage?: Stage | null;
  ms?: number | null;
  ts: string;
}

export interface Citation {
  chunk_id: string;
  document_id?: string | null;
  title?: string;
  snippet?: string;
  score?: number;
  source?: string;
}

export interface ToolResultPayload {
  name: string;
  args?: Record<string, unknown>;
  ok: boolean;
  output?: unknown;
  error?: string | null;
  ms?: number;
  risk?: string;
}

export interface HitlPayload {
  tool: string;
  args?: Record<string, unknown>;
  reason?: string;
}

export interface TraceNode {
  id: string;
  stage: string;
  name: string;
  status: string;
  ms: number;
  tokens: number;
  cost: number;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  children?: TraceNode[];
}

export interface Session {
  id: string;
  title: string;
  created_at?: string | null;
}

export interface RunSnapshot {
  id: string;
  session_id: string;
  status: string;
  model_version?: string;
  prompt_version?: string;
  query?: string;
  answer?: string;
  citations?: Citation[];
  tool_results?: ToolResultPayload[];
  ended_at?: string | null;
}

export interface RunRef {
  id: string;
  session_id: string;
  status: string;
  model_version?: string;
  prompt_version?: string;
  query?: string;
  answer?: string;
  citations?: Citation[];
  tool_results?: ToolResultPayload[];
  ended_at?: string | null;
}
export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: "member" | "admin";
}

export interface Ticket {
  id: string;
  ticket_id: string;
  title: string;
  detail: string;
  severity: "P0" | "P1" | "P2" | "P3";
  status: "created" | "in_progress" | "resolved" | "closed";
  created_at: string;
  updated_at: string;
}

export interface TicketPage {
  items: Ticket[];
  total: number;
  page: number;
  page_size: number;
}
