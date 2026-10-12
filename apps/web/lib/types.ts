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
  cursor?: string | null;
  type: EventType;
  run_id: string;
  payload?: Record<string, unknown> | null;
  stage?: Stage | null;
  ms?: number | null;
  ts: string;
}

export interface Citation {
  chunk_id: string;
  citation_id?: string | null;
  document_id?: string | null;
  title?: string;
  snippet?: string;
  score?: number;
  source?: string;
  source_url?: string;
  heading?: string;
  retrieval_method?: string;
}

export interface PlanStep {
  id: string;
  kind: "retrieve" | "tool" | "answer";
  goal: string;
  tool: string | null;
  args: Record<string, unknown>;
  depends_on: string[];
  status: "pending" | "running" | "done" | "failed" | "denied" | "skipped";
}

export interface ExecutionPlan { version: 1; steps: PlanStep[] }

export interface RetrievalDiagnostic {
  mode?: "echo" | "graph";
  status?: "not_executed" | "unavailable" | "no_documents" | "no_match" | "hit";
  reason?: string;
  method?: "hybrid" | "keyword";
  degraded?: boolean;
  warnings?: string[];
  error_type?: string;
  error_types?: Record<string, string>;
}

export interface ChunkPreview {
  citation_id: string;
  document_id: string;
  title: string;
  source_url: string;
  heading: string;
  content: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  source: string;
  version: string;
  created_at?: string | null;
  chunks: number;
  embedded: number;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  content: string;
}

export interface ToolResultPayload {
  name: string;
  step_id?: string;
  args?: Record<string, unknown>;
  ok: boolean;
  output?: unknown;
  error?: string | null;
  ms?: number;
  risk?: string;
}

export interface HitlPayload {
    tool: string;
    approval_id: string;
  args: Record<string, unknown>;
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
  plan?: ExecutionPlan;
  approval?: HitlPayload;
  model_version?: string;
  prompt_version?: string;
  query?: string;
  answer?: string;
  citations?: Citation[];
  retrieval?: RetrievalDiagnostic;
  tool_results?: ToolResultPayload[];
  ended_at?: string | null;
}

export interface RunRef {
  id: string;
  session_id: string;
  status: string;
  plan?: ExecutionPlan;
  approval?: HitlPayload;
  model_version?: string;
  prompt_version?: string;
  query?: string;
  answer?: string;
  citations?: Citation[];
  retrieval?: RetrievalDiagnostic;
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
export type EvalSource = {
  environment: "local" | "staging" | "ci";
  golden_set_version: string;
  code_dirty: boolean;
  cheap_model: string;
  llm_configured: boolean;
  database_configured: boolean;
  embedding_configured: boolean;
  rerank_configured: boolean;
  configured_retrieval_mode: "hybrid" | "bm25" | "unavailable";
  tool_data_source: "sample";
  agent_flags: { mode: "graph"; routing: boolean; retry: boolean; dynamic: boolean };
};

export type EvalReport = {
  status: "empty" | "ready";
  id: string | null;
  started_at: string | null;
  generated_at: string | null;
  git_sha: string;
  prompt_version: string;
  model_version: string;
  source: EvalSource | null;
  metrics: {
    cases?: number;
    citation_skipped?: number;
    task_success_rate?: number;
    tool_accuracy?: number;
    p50_latency_ms?: number;
    p95_latency_ms?: number;
    recall_at_5?: number | null;
    avg_tokens?: number | null;
    cost_per_task?: number | null;
    failure_stages?: Record<string, number>;
  };
  report_path: string;
};
