# 部署说明（Neon + Railway + Vercel）

目标形态：前端 Vercel（静态构建） + 后端 Railway（常驻容器） + Neon Postgres（pgvector）。
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
`sessions / runs / documents / chunks / traces / eval_runs`。应用启动只做数据库连通性检查，不自动改表。

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
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI 兼容模型（DeepSeek / Qwen / OpenAI） | 否（缺省走离线兜底） |
| `LLM_MODEL_CHEAP` / `LLM_MODEL_STRONG` | 成本档位路由 | 否 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | 向量化；缺省则检索退化为 BM25 | 否 |
| `RERANK_ENABLED` / `RERANK_BASE_URL` / `RERANK_API_KEY` / `RERANK_MODEL` | 重排；缺省跳过 | 否 |
| `CORS_ORIGINS` | 逗号分隔，含 Vercel 域名与 preview 域名 | 是 |
| `REDIS_URL` | Upstash 等；缺省用进程内缓存 | 否 |
| `API_TOKEN` | 简易鉴权；缺省不启用 | 否 |
| `AGENT_MODE` | `echo`（离线跑通）/ `graph`（LangGraph 编排） | 否，默认 echo |
| `LANGFUSE_*` | 可观测；缺省不启用 | 否 |

## 5. 上线后冒烟顺序

1. `GET /healthz` → `db.connected = true`
2. `POST /ingest` 灌入 2–3 篇文档 → 返回 `chunks` 与 `embedded`
3. `POST /runs` 提交问题 → `GET /runs/{id}/stream` 观察 plan / retrieve / tool_result
4. 触发建单类问题 → 出现 `hitl_request` → `POST /runs/{id}/resume` 确认后继续执行
5. `GET /traces/{run_id}` 回放

启用 `API_TOKEN` 后，Railway 与 Vercel 都要配置同一个令牌。浏览器通过 Vercel 的服务端代理登录，令牌只用于服务端向 Railway 发起请求，不会进入前端构建产物；登录会话使用 HttpOnly Cookie，默认 8 小时过期。

## 6. 本地一键启动（备选）

```bash
docker compose -f infra/docker-compose.yml up --build
```

> 本机未安装 Docker 时，可用 `uv run uvicorn apps.api.src.main:app --port 8000` 直接起后端，
> 前端 `cd apps/web && pnpm dev`（Next.js 服务端路由代理 `/api` 请求）。
