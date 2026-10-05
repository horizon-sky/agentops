# AgentOps 项目协作指南

本文件适用于整个仓库。开始修改前，先读相关模块的当前实现和测试；`README.md` 描述产品目标与演示能力，实际行为以代码和测试为准。默认用中文沟通，代码标识符与命令保持原文。

## 项目定位与链路

这是面向研发工单场景的 Agent 工作台。前端使用 Next.js 15 App Router；后端使用 Python 3.12、FastAPI、LangGraph；数据层计划使用 Neon Postgres + pgvector。目标部署为 Vercel 前端和 Railway 后端容器，当前仍处于上线准备阶段，不要把本地降级演示当作生产联调结果。

主要请求链路：`apps/web` 通过 `/api/*` 服务端路由访问 FastAPI，将 HttpOnly 登录 Cookie 转为个人 Bearer token，并携带服务端代理凭据；`POST /runs` 创建执行，`GET /runs/{id}/stream` 订阅 SSE；`GraphRunner` 按 `classify -> plan -> retrieve -> tools -> review -> answer` 执行，写工具通过 `interrupt` 等待 `POST /runs/{id}/resume`。`AGENT_MODE` 默认是 `echo`，验证真实图编排时须显式设为 `graph`。

## 目录与入口

| 路径 | 职责 |
| --- | --- |
| `apps/api/src/main.py`、`apps/api/src/routers/` | FastAPI 装配、健康检查、会话、运行、文档入库、追踪与评测接口 |
| `apps/api/src/sse.py` | 进程内事件总线、SSE 推送与历史事件 |
| `apps/web/app/`、`components/`、`lib/` | 页面、交互组件、API 客户端与运行状态 |
| `src/agent/graph.py`、`runner.py`、`nodes/` | 图装配、执行器和各阶段节点 |
| `src/agent/model.py`、`checkpointer.py` | 模型适配、离线降级与 LangGraph 检查点 |
| `src/rag/` | 文档解析、切分、Embedding、混合检索、Rerank 与入库 |
| `src/tools/`、`services/mcp_*/` | 工具注册/执行与 MCP 服务 |
| `src/db/` | SQLAlchemy 模型、会话和缓存 |
| `evals/`、`tests/` | 黄金集评测与自动化测试 |
| `scripts/`、`infra/`、`docs/deploy.md` | 初始化、自检、本地容器与部署说明 |

配置入口是 `src/config.py`，变量示例见 `.env.example`。不要提交 `.env`、密钥、真实用户数据或评测生成物。修改数据库模型、API 事件或前端类型时，同时核对跨模块契约。

## 本地运行与验证

从仓库根目录执行：

```bash
uv sync --locked --extra dev
uv run --extra dev ruff check .
uv run --extra dev pytest -q
uv run uvicorn apps.api.src.main:app --port 8000
```

前端在 `apps/web` 下执行 `pnpm install --frozen-lockfile`、`pnpm dev`；修改前端后运行 `pnpm exec tsc --noEmit` 和 `pnpm build`。本地默认代理目标为 `http://127.0.0.1:8000`，部署时由 `API_PROXY_TARGET` 指向 Railway。外部服务测试须显式配置环境；无密钥或数据库时的通过结果只证明降级路径。

## 修改约定

- 先明确目标和验收方式，再做最小范围修改；发现不确定的业务要求时说明假设。
- 修复缺陷时优先添加能复现问题的回归测试，并运行受影响测试与相应检查。
- 不顺手重构相邻模块；新变更产生的无用导入和代码应清理。
- 写类工具必须经过 HITL 确认；拒绝或未确认时不得执行。涉及该链路的修改要覆盖拒绝、批准与恢复行为。
- RAG 与模型适配器保持当前接口：`aembed`、`arank`、`acomplete`、`astream`。降级时如实报告无数据，不伪造引用、成功率或外部调用结果。
- `uv.lock` 和 `apps/web/pnpm-lock.yaml` 与依赖声明同步更新；不要只改依赖清单。

## 上线前的已知缺口

已建立 Alembic 迁移，`scripts/init_db.py` 负责初始化 pgvector、账号与业务表；应用启动只检查连接。`runs` 状态写入数据库，但 SSE 事件总线、后台任务与请求限流仍在进程内，因此部署保持单副本。浏览器端支持公开注册、邮箱验证及可撤销登录会话，业务资源按用户隔离；公开上线前须验证 Resend 邮件、Postgres 迁移及跨账号访问。Railway 容器与 CI 配置见 `docs/deploy.md`；发布前仍需核对远程仓库、平台变量和 staging 冒烟结果。
