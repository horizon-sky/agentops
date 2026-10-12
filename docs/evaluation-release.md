# 评测看板发布与验收

首版仅展示最新已发布报告；入口、页面和接口都需要管理员权限。
`eval_runs` 存储汇总数据，容器内不需要 `evals/report.json`，重新部署不会删除报告。
评测不在 HTTP 请求中执行，没有历史对比、网页发起或自动定时任务。

## 1. 同库隔离

复用现有 Postgres，在每次运行时创建随机 `agentops_eval_<uuid>` schema，迁移完整业务表。
评测账号、固定测试文档、会话、工单、追踪和检查点均使用该 schema；结束后删除它。
不发送邮件，不修改生产管理员，不自动发布报告到生产业务 schema。
评测始终关闭共享 Redis，仅使用进程内缓存，避免向业务缓存写入测试数据。
需要已有 pgvector 扩展、创建/删除 schema 和执行迁移的数据库权限。
Neon pooled 端点不支持检查点隔离所需的 startup search_path，评测使用同一数据库的 direct
端点；生产应用继续使用原 pooled 端点。

只验证数据库迁移与报告事务，不调用模型：

```bash
uv run python -m scripts.evaluate_isolated --env-file .env --storage-check
```

运行少量黄金集，真实 Postgres + 离线模型，默认关闭模型、Embedding、Rerank 的付费调用：

```bash
uv run python -m scripts.evaluate_isolated --env-file .env --limit 5
```

完成代码提交并审查配置后，操作人员显式添加 `--with-model` 才启用已配置外部服务：

```bash
# 先小批量检查模型、检索与审批链路
uv run python -m scripts.evaluate_isolated --env-file .env --limit 5 --with-model
# 审查小批量结果后执行全量；没有 --limit 才是完整黄金集
uv run python -m scripts.evaluate_isolated --env-file .env --with-model
```

固定测试文档为 `eval-fixture-v1`，只包含排查及审批规则，不代表生产知识库覆盖程度。
前 40 条用例只覆盖 incident/code；完整黄金集还包含 knowledge、ticket、injection、general。
全量结果可能不通过，必须如实保留，不能用预估数字补齐。

原 `uv run python -m evals.runner` 入口仍可用于离线或操作人员已准备的独立环境；
配置数据库时要求 `--user-id` 是该环境的已验证账号，生产 APP_ENV 拒绝直接执行。
同库评测应使用上面的隔离入口，不直接指定日常账号。

## 2. 报告审查

脚本只在选定用例全部完成后原子替换 `evals/report.json`，并生成 Markdown。
运行异常会保留上一份完整报告；要确认输出的新报告 ID、完成时间与本次执行一致。
失败用例的完整报告可以发布；中途中止、损坏及旧格式报告会被发布命令拒绝。

报告包含 UUID、schema_version=1、实际开始/完成时间、SHA、主/轻量模型、Prompt、黄金集版本，
以及环境、模型配置、检索配置、功能开关、样例工具来源和源码未提交修改标记。
正式发布应使用已提交源码，确认 `source.code_dirty=false`；SHA 不表示线上部署已匹配该版本。
检索模式记录配置意图，运行时可能回退 BM25，并不宣称各用例都成功使用向量检索。
当前 Recall@5、Token、费用没有完整测量，使用 null；成本单位约定 USD。

JSON 中的逐例结果留在执行机器供审查，不进入生产数据库。报告和临时文件均被 Git/Docker 忽略。
报告不存在、模型离线及引用断言跳过都是不同状态，不把跳过项宣称为检索验证通过。

## 3. 上线顺序

1. 审查变更，在独立 schema 完成存储验收和评测，不改现有工作区的其他内容。
2. 在后端目标环境执行 `python scripts/init_db.py`，确认迁移 head 为 `0007_eval_reports`。
   Railway 继续通过原 `preDeployCommand` 迁移；确认其成功后部署后端，再部署前端。
3. 指定已注册、已验证且启用的账号。若还不是管理员，在受控环境执行
   `python -m scripts.manage_users --email <邮箱> --role admin`，重新登录；该命令撤销旧会话。
4. 将审查后的 JSON 放到受控执行环境，明确该命令的 DATABASE_URL 指向目标业务数据库：

```bash
uv run python -m scripts.publish_eval_report --report evals/report.json --email <管理员邮箱>
```

目标账号必须已验证、启用且为管理员。同 UUID 同汇总数据重复发布成功且不新增记录，
同 UUID 不同内容拒绝；延迟发布旧报告不会覆盖最新完成报告。
发布命令只写目标业务 schema 的 `eval_runs`，不复制评测账号、会话、工单或文档。
不存在 HTTP 上传/发布接口。源码和报告可以分开部署，不必把评测工具加入 Railway 镜像。

## 4. 接口与验收

`GET /eval/report` 继续需要个人身份和服务端代理鉴权：

- 401：未登录；403：非管理员；503：账号数据库或报告读取暂时不可用。
- 200 / `status=empty`：无已发布完整报告，metrics={}，generated_at=null。
- 200 / `status=ready`：最新完成报告，包含 ID、metrics、真实开始/完成时间、版本与 source。
- `report_path` 为兼容保留的空字符串，不暴露执行机器路径；旧迁移记录不自动视为有效报告。

浏览器验收：管理员导航有入口，普通账号没有；直接访问仍受保护。确认指标与 JSON 一致，
0% 正常显示，null 显示“未测量”；无报告和服务错误分开显示，错误可以重试。
确认独立环境和样例指标工具说明、版本、报告 ID、完成时间。刷新时间不变。
重新部署后端后仍能读取报告，普通业务账号看不到评测文档、会话和工单。

本地检查：

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest -q
# apps/web 下
pnpm exec tsc --noEmit
pnpm build
node tests/eval-dashboard.mjs
node tests/auth-smoke.mjs
```

SQLite 回归与模拟服务的前端测试不代替真实 Postgres、付费模型或线上浏览器验收。
功能验收不设置臆造成功率门槛；现有 CI 门禁仍是离线、部分黄金集回归，不自动向线上发布。

## 5. 回滚

回滚前后端应用版本，保留新数据库字段和已发布报告，不执行删除字段的 downgrade。
旧版本仍读本地文件，回滚后可能重新显示空指标，须明确说明。
删除临时评测 schema 只清理本次测试数据，生产 `eval_runs` 报告不会随之删除。

## 6. 本次实施验证（2026-10-12）

- 后端 `ruff check .` 通过；完整 `pytest`：152 passed。
- 前端 TypeScript、生产构建、看板状态渲染、认证代理冒烟通过。
- Chrome 本地浏览器验证加载、正常、无报告、503 与重试，0% 与未测量、刷新时间不变，
  管理员入口与普通账号限制；桌面和手机宽度的看板内容检查通过。
- 现有 Postgres 的随机 schema 验证迁移、发布事务、并发幂等与冲突拒绝，测试数据已清理。
  另验证旧版本 0006 到 0007 的增量迁移，旧指标保留且完成时间为空。
- 真实 Postgres + 离线模型完成 5 条黄金集冒烟，临时账号、文档、运行及检查点 schema 已清理。

按用户授权在现有业务数据库新增专用验收管理员（随机密码只保存本机临时文件），
线上浏览器已验证该账号登录、管理员导航入口及退出。当前线上报告接口仍为旧契约且指标为空，
因此这次检查没有验证新版报告链路。

尚未执行付费模型全量黄金集、生产业务 schema 迁移与报告发布，
尚未完成新版应用线上浏览器及后端重新部署验收。
