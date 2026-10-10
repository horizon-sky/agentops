const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const { renderToStaticMarkup } = require("react-dom/server");
const React = require("react");

function load(file, dependencies = {}) {
  const source = fs.readFileSync(path.join(__dirname, file), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const sandbox = { exports: {}, URL, require: name => dependencies[name] ?? require(name) };
  vm.runInNewContext(compiled, sandbox);
  return sandbox.exports;
}

const tables = load("../lib/replyTables.ts");
const citations = load("../lib/citations.ts");
const MessageContent = load("../components/MessageContent.tsx", {
  "@/lib/replyTables": tables, "@/lib/citations": citations,
}).default;
const parse = text => tables.replyTableAt(text.split("\n"), 0);
const plain = value => JSON.parse(JSON.stringify(value));
const citation = { citation_id: "source-1", chunk_id: "hash", snippet: "原文" };
const render = text => renderToStaticMarkup(React.createElement(MessageContent, {
  text, citations: [citation], onCitation: () => {},
}));

const screenshot = "| 步骤 | 需要补充或检查的证据 | 目的 |\n|---|---|---|\n" +
  "| 1. 确定影响范围 | **接口路径**、请求 ID | 确定受影响接口 |\n" +
  "| 2. 定位耗时环节 | `trace_id` [source-1] | 排查服务、数据库及下游 |";
const html = render("建议按以下顺序处理：\n" + screenshot + "\n\n这张表是建议的排查流程。");
assert.match(html, /<table class="reply-table">/);
assert.equal((html.match(/<th /g) ?? []).length, 3);
assert.equal((html.match(/<td /g) ?? []).length, 6);
assert.match(html, /<strong>接口路径<\/strong>/);
assert.match(html, /<code>trace_id<\/code>/);
assert.match(html, /class="reply-citation"/);
assert.match(html, /role="region" aria-label="回复数据表格" tabindex="0"/);
assert.match(html, /建议按以下顺序处理：/);
assert.match(html, /这张表是建议的排查流程。/);

const aligned = parse("字段 | 数值 | 说明\n:--- | ---: | :---:\na | 12 | 好\n");
assert.deepEqual(plain(aligned.alignments), ["left", "right", "center"]);
assert.equal(aligned.nextLine, 3);
assert.deepEqual(plain(parse("| A | B |\n|--|--|\n| a\\|b | |\n| c |\n").rows), [
  ["a|b", ""], ["c", ""],
]);
assert.equal(parse("ordinary | text\nmore | words"), null);
assert.equal(parse("| A | B |\n|---|"), null);
assert.equal(parse("| A | B |\n|--"), null);
assert.doesNotMatch(render("ordinary | text\nmore | words"), /<table/);
assert.doesNotMatch(render("```text\n" + screenshot + "\n```"), /<table/);
assert.match(render("```text\n" + screenshot + "\n```"), /<pre><code>/);
assert.match(render("| A | B |\r\n|---|---|\r\n| 1 | 2 |"), /<table/);
assert.match(render("| A | B |\n|---|---|\n| <script>alert(1)</script> | 2 |"), /&lt;script&gt;/);
assert.doesNotMatch(render("| A | B |\n|---|---|\n| <script>alert(1)</script> | 2 |"), /<script>/);
assert.equal((render(screenshot + "\n\n" + screenshot).match(/<table /g) ?? []).length, 2);
assert.doesNotMatch(render("| A | B |\n|--"), /<table/);
assert.match(render("| A | B |\n|---|---|\n| streaming"), /<table/);

const tree = MessageContent({ text: screenshot, citations: [citation], onCitation: id => {
  assert.equal(id, "source-1");
  clicked = true;
} });
let clicked = false;
function visit(node) {
  if (Array.isArray(node)) return node.forEach(visit);
  if (!node || typeof node !== "object") return;
  if (node.type === "button" && node.props.className === "reply-citation") node.props.onClick();
  visit(node.props?.children);
}
visit(tree);
assert.equal(clicked, true);
console.log("Reply table parsing, rendering, streaming and citation tests passed");
