const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(path.join(__dirname, "../lib/auth.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const valid = {
  captcha_id: "62e4e40a-29d1-4d1d-9a25-66dd8a48d205",
  image_data_url: "data:image/png;base64,iVBORw0KGgo=",
  expires_at: "2099-01-01T00:00:00Z",
};
let response = { ok: true, data: valid };
let request;
const sandbox = {
  exports: {},
  fetch: async (url, options) => {
    request = { url, options };
    return { ok: response.ok, json: async () => response.data };
  },
};
vm.runInNewContext(compiled, sandbox);

module.exports = (async () => {
  await sandbox.exports.authRequest("captcha");
  assert.equal(request.options.cache, "no-store", "Authentication requests must not cache captcha responses");
  const data = await sandbox.exports.requestRegistrationCaptcha();
  assert.equal(JSON.stringify(data), JSON.stringify(valid));
  assert.equal(request.url, "/api/auth/captcha");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.credentials, "same-origin");
  assert.equal(request.options.headers["X-AgentOps-CSRF"], "1");
  assert.equal(request.options.body, "{}");
  for (const malformed of [
    null, {}, { ...valid, captcha_id: "not-a-uuid" },
    { ...valid, image_data_url: "data:text/html;base64,PHNjcmlwdD4=" },
    { ...valid, image_data_url: "data:image/png;base64," },
    { ...valid, expires_at: "invalid" },
  ]) {
    response = { ok: true, data: malformed };
    await assert.rejects(sandbox.exports.requestRegistrationCaptcha(), /验证码服务响应异常/);
  }
  response = { ok: false, data: { detail: "验证码服务暂不可用" } };
  await assert.rejects(sandbox.exports.requestRegistrationCaptcha(), /验证码服务暂不可用/);
  console.log("PASS: captcha client request, response validation and server errors");
})();
if (require.main === module) {
  module.exports.catch((error) => { console.error(error); process.exitCode = 1; });
}
