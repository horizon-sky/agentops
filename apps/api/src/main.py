"""FastAPI 应用装配：CORS、路由、健康检查与统一异常处理。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.src.deps import cache_dep
from apps.api.src.routers import auth, documents, ingest, runs, sessions, tickets, traces
from apps.api.src.routers import eval as eval_router
from apps.api.src.schemas.api import HealthOut
from src.agent.graph import close_graphs
from src.config import Settings, get_settings
from src.db.session import db_status, dispose_engine, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("agentops.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.has_database:
        try:
            if await init_db(settings):
                logger.info("数据库连通性检查通过")
        except Exception:  # noqa: BLE001 - 启动阶段失败不应导致进程退出
            logger.exception("数据库连通性检查失败")
    else:
        logger.warning("未配置 DATABASE_URL，服务以内存降级模式运行")
    try:
        yield
    finally:
        await close_graphs()
        await dispose_engine()


def create_app() -> FastAPI:
    settings: Settings = get_settings()
    if settings.app_env == "production" and (
        not settings.api_token or not settings.has_database
    ):
        raise RuntimeError("production requires DATABASE_URL and API_TOKEN")
    app = FastAPI(
        title="AgentOps API",
        description="研发工单自动化 Agent 系统后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(runs.router)
    app.include_router(ingest.router)
    app.include_router(documents.router)
    app.include_router(tickets.router)
    app.include_router(traces.router)
    app.include_router(eval_router.router)

    @app.get("/healthz", response_model=HealthOut, tags=["ops"])
    async def healthz() -> HealthOut:
        cache = cache_dep()
        return HealthOut(
            status="ok",
            env=settings.app_env,
            db=await db_status(settings),
            cache="redis" if not cache.degraded else "memory-fallback",
            llm=settings.strong_model if settings.has_llm else "echo-offline",
            embedding=settings.embedding_model if settings.has_embedding else "disabled",
            rerank=settings.rerank_model if settings.rerank_enabled else "disabled",
            prompt_version=settings.prompt_version,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 path=%s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    return app


app = create_app()
