// Render the real presentation component; no network, accounts or browser required.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const path = fileURLToPath(new URL("../components/EvalReportView.tsx", import.meta.url));
const compiled = ts.transpileModule(readFileSync(path, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const mod = { exports: {} };
new Function("require", "module", "exports", compiled)(require, mod, mod.exports);
const View = mod.exports.default;
const render = (props) => renderToStaticMarkup(React.createElement(View, {
  loading: false, error: "", report: null, onReload() {}, ...props,
}));

const loading = render({ loading: true });
assert.match(loading, /role="status"/);
const empty = render({ report: { status: "empty", metrics: {} } });
assert.match(empty, /尚未发布评测报告/);
assert.ok(!empty.includes("任务成功率"));
const failed = render({ error: "报告读取失败" });
assert.match(failed, /role="alert"/);
assert.match(failed, /重试/);
assert.ok(!failed.includes("尚未发布评测报告"));

const report = {
  status: "ready", id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  generated_at: "2026-10-12T00:01:00Z", started_at: "2026-10-12T00:00:00Z",
  git_sha: "a".repeat(40), model_version: "test-model", prompt_version: "test-prompt",
  source: {
    environment: "staging", golden_set_version: "test-golden", llm_configured: true,
    code_dirty: false, cheap_model: "test-model-cheap",
    database_configured: true, embedding_configured: false, rerank_configured: false,
    configured_retrieval_mode: "bm25", tool_data_source: "sample",
    agent_flags: { mode: "graph", routing: false, retry: false, dynamic: false },
  },
  metrics: {
    cases: 2, citation_skipped: 0, task_success_rate: 0, tool_accuracy: 75,
    p50_latency_ms: 100, p95_latency_ms: 200,
    recall_at_5: null, avg_tokens: null, cost_per_task: null,
    failure_stages: { retrieve: 2 },
  },
};
const ready = render({ report });
assert.match(ready, /0%/); // Zero success is a measured result, never "unmeasured".
assert.match(ready, /75%/);
assert.match(ready, /100 ms/);
assert.match(ready, /200 ms/);
assert.match(ready, /独立环境评测/);
assert.match(ready, /样例指标工具/);
assert.match(ready, /未测量/);
assert.match(ready, /检索/);
assert.match(ready, /test-model/);
assert.match(ready, /test-golden/);
assert.ok(!ready.includes("v1 · 基线"));
const unavailable = render({ report: { ...report, metrics: {}, source: {
  ...report.source, llm_configured: false, database_configured: false,
  configured_retrieval_mode: "unavailable",
} } });
assert.match(unavailable, /离线降级/);
assert.match(unavailable, /未测量/);
assert.ok(!unavailable.includes("undefined") && !unavailable.includes("NaN"));
console.log("PASS: evaluation loading, empty, failure/retry, real zero, unmeasured and provenance states");
