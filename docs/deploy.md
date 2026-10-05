# 部署说明（Neon + Railway + Vercel）

目标形态：前端 Vercel（Next.js 服务端路由与页面） + 后端 Railway（常驻单副本容器） + Neon Postgres（pgvector）。
后端预算控制在 **$15/月以内**：服务内存 1GB 起步，并在 Railway 后台设置 spend limit。

## 1. Neon：创建 Postgres 并启用 pgvector

1. 在 Neon 创建项目，复制 **pooled connection** 连接串；
2. 连接串形如：
   `postgresql+asyncpg://user:pass@ep-xxx-pooler.<region>.aws.neon.tech/agentops?sslmode=require`
3. 在 `.env` 中填入 `DATABASE_URL`；
4. 本地初始化表与扩展：

```bash
uv run python scripts/init_db.py
```

该脚本通过 Alembic 执行版本化迁移，首个迁移会执行 `CREATE EXTENSION IF NOT EXISTS vector` 并创建
`sessions / runs / documents / chunks / traces / eval_runs`；`0002_accounts` 增加
`users / auth_sessions / auth_tokens`，为会话和文档补充归属。应用启动只检查连接，不自动改表。
升级前备份；历史数据归属禁用的 `archive@agentops.invalid`，不会向新注册账号开放。

## 2. Railway：部署 FastAPI 容器

1. 连接 GitHub 仓库，选择根目录；Railway 会读取 `railway.json`（Dockerfile：`apps/api/Dockerfile`）；
2. 在 Variables 中配置环境变量（见下方清单）；
3. 健康检查路径 `/healthz`，失败自动重启（最多 5 次）；
4. 部署完成后访问 `https://<service>.up.railway.app/healthz` 确认返回 `status: ok`；
5. **成本控制**：后台设置 spend limit；内存从 1GB 起步；首月用 Usage 页观察实际花费后回调规格。

Railway 使用 `railway.json` 的 `preDeployCommand` 在每次部署前执行迁移：

```bash
python scripts/init_db.py
```

迁移成功后再将服务切换到生产流量；应用启动不会自动创建表或修改 schema。

> 注意：Railway 官方定价页在本次方案设计时三次抓取均超时，README 与本文只记录实测值，不写未核实的单价。

## 3. Vercel：部署前端（Next.js 15）

1. Import 仓库，Root Directory 设为 `apps/web`；
2. Framework 自动识别为 Next.js（已提供 `vercel.json`）；
3. 环境变量：
   - `NEXT_PUBLIC_API_BASE_URL=/api`（同源前缀）
   - `API_PROXY_TARGET=https://<service>.up.railway.app`（服务端代理目标）
   - `API_TOKEN=<与 Railway 相同的令牌>`（服务端变量，不要加 `NEXT_PUBLIC_` 前缀）
4. 前端所有请求走 `/api/*`，由 Next.js 服务端路由转发到后端，**前端与后端同源，无需配置 CORS**。

提交代码到远程仓库后，先在 Vercel 绑定 `apps/web` 为 Root Directory，再配置上述三个变量并分别部署 Preview/Production。

## 4. 环境变量清单

| 变量 | 说明 | 必填 |
| --- | --- | --- |
| `DATABASE_URL` | Neon 连接串（pooled，asyncpg 驱动） | 是 |
| `APP_ENV` | Railway 设为 `production`，缺数据库或代理凭据时拒绝启动 | 是 |
| `WEB_ORIGIN` | 邮件链接对应的前端来源，如 `https://agentops.example.com` | 是 |
| `RESEND_API_KEY` / `MAIL_FROM` | Resend 凭据与已验证域名发件地址，如 `AgentOps <account@example.com>` | 是 |
| `AUTH_SESSION_HOURS` | 登录有效期，默认 8 小时，上限 24 小时 | 否 |
| `MAX_ACTIVE_RUNS_PER_USER` / `MAX_RUNS_PER_USER_PER_DAY` | 默认同时运行/待审批 2 个、UTC 每天 50 次 | 否 |
| `MAX_INGESTS_PER_USER_PER_DAY` | 默认 24 小时内上传 20 次（进程内限流） | 否 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI 兼容模型（DeepSeek / Qwen / OpenAI） | 否（缺省走离线兜底） |
| `LLM_MODEL_CHEAP` / `LLM_MODEL_STRONG` | 成本档位路由 | 否 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | 向量化；缺省则检索退化为 BM25 | 否 |
| `RERANK_ENABLED` / `RERANK_BASE_URL` / `RERANK_API_KEY` / `RERANK_MODEL` | 重排；缺省跳过 | 否 |
| `CORS_ORIGINS` | 直接跨源调用时允许的来源；通过同源 Next.js 代理无需 CORS | 否 |
| `REDIS_URL` | Upstash 等；缺省用进程内缓存 | 否 |
| `API_TOKEN` | Railway 与 Vercel 相同的服务端代理凭据，仅通过 `X-API-Token` 验证；不代表用户身份 | 生产必填 |
| `AGENT_MODE` | `echo`（离线跑通）/ `graph`（LangGraph 编排） | 否，默认 echo |
| `LANGFUSE_*` | 可观测；缺省不启用 | 否 |

## 5. 上线后冒烟顺序

1. `GET /healthz` → `db.connected = true`；在独立 staging 数据库验证迁移与旧数据归档。
2. 浏览器注册两个账号，确认收到真实邮件；验证前登录 403，点击确认后可登录；重复/过期链接拒绝。
3. 检查登录响应不含个人令牌或代理凭据，Cookie 为 `HttpOnly; Secure; SameSite=Lax`；伪造来源或缺少 `X-AgentOps-CSRF: 1` 的写请求返回 403。
4. 登录后创建会话、通过 `POST /ingest` 上传私有文档，提交任务并观察 SSE；另一账号访问会话、运行、审批、追踪返回空列表或 404，检索不能命中其他账号文档。
5. `AGENT_MODE=graph` 触发写工具；未确认/拒绝不执行，确认后继续；其他用户不能恢复该任务。
6. 退出、密码重置或禁用账号后旧会话返回 401，已连接 SSE 最迟约 15 秒重新检查身份并关闭；使用新密码重新登录。
7. 普通账号评测接口 403，管理员可访问；核对限流与任务额度 429，不将无模型离线结果作为真实联调结果。

Railway 与 Vercel 配置相同 `API_TOKEN`，禁止使用 `NEXT_PUBLIC_API_TOKEN`。浏览器使用邮箱密码登录，个人会话令牌只存 HttpOnly Cookie，Next.js 向 Railway 注入个人 Bearer token 和代理凭据。注册、重发与找回返回统一提示；发信失败 503 并回滚事务。验证/重置链接 30 分钟有效，重发会使旧链接失效，密码重置撤销所有会话。Preview 应使用独立数据库、邮件配置和对应 `WEB_ORIGIN`。

首位管理员先正常注册并验证邮箱，再在受控环境执行：

```bash
uv run python -m scripts.manage_users --email admin@example.com --role admin
# 可选：将迁移前的归档会话与文档交给该管理员
uv run python -m scripts.manage_users --email admin@example.com --role admin --claim-legacy
# 禁用/启用账号（同时撤销现有会话）
uv run python -m scripts.manage_users --email user@example.com --disable
uv run python -m scripts.manage_users --email user@example.com --enable
# 真实数据库评测，只能使用指定的已验证账号资源
uv run python -m evals.runner --limit 40 --user-id <verified-user-uuid>
```

没有默认管理员或共享登录密码。管理员也只能访问自己拥有的业务资源。后端保持一个 worker、一个副本；事件总线、任务和注册/登录/上传限流仍在内存中，重启会清空限流。多副本需要共享任务、事件与限流存储。

本地后端回归测试使用 SQLite 和模拟邮件，不能替代 Postgres 行锁、迁移、pgvector 与真实邮件验证。
前端在 `apps/web` 执行 `pnpm exec tsc --noEmit`、`pnpm build`、`node tests/auth-smoke.mjs`；
最后一项启动生产 Next.js 与本地模拟后端，验证 Cookie、CSRF、代理身份与页面保护，不发送真实邮件，也不等同浏览器交互测试。

## 6. 本地一键启动（备选）

```bash
docker compose -f infra/docker-compose.yml up --build
```

> 本机未安装 Docker 时，可用 `uv run uvicorn apps.api.src.main:app --port 8000` 直接起后端，
> 前端 `cd apps/web && pnpm dev`（Next.js 服务端路由代理 `/api` 请求）。
