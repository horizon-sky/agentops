"""真实 Postgres/模型冒烟；只在随机隔离 schema 中操作，结束后清理。

运行：uv run python -m scripts.smoke_ticket_rag
需要已配置 DATABASE_URL、LLM；使用现有 Embedding 配置，不发送邮件。
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from apps.api.src.deps import db_dep, settings_dep
from apps.api.src.main import create_app
from apps.api.src.routers.runs import _persist_run_result
from src.agent.graph import close_graphs
from src.agent.runner import GraphRunner
from src.auth import token_digest
from src.config import Settings
from src.db import session as db_runtime
from src.db.models import AuthSession, Run, Session, Ticket, User
from src.db.ticket_backfill import backfill_tickets
from src.rag.hybrid_search import hybrid_search
from src.tickets import TicketFields, persist_ticket


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def verify(settings: Settings, schema: str) -> None:
    url = make_url(settings.database_url).set(drivername="postgresql+asyncpg")
    if "sslmode" in url.query:
        url = url.update_query_dict({"ssl": url.query["sslmode"]})
    url = url.difference_update_query(["sslmode", "channel_binding", "options"])
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"timeout": 20},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def use_schema(connection, _record):
        connection.run_async(lambda raw: raw.execute(f'SET search_path TO "{schema}", public'))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    db_runtime._engine, db_runtime._session_factory = engine, factory
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: settings

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[db_dep] = database
    try:
        async with engine.connect() as conn:
            require(
                await conn.scalar(text("SELECT current_schema()")) == schema,
                "异步数据库连接未使用隔离 schema",
            )
            require(
                bool(
                    await conn.scalar(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema=:schema AND table_name='runs' "
                            "AND column_name='retrieval'"
                        ),
                        {"schema": schema},
                    )
                ),
                "隔离迁移缺少 retrieval 列",
            )
        now = datetime.now(UTC)
        async with factory() as db:
            users = [
                User(
                    email=f"{uuid.uuid4().hex}@smoke.invalid",
                    display_name="Smoke",
                    password_hash="unused",
                    verified_at=now,
                )
                for _ in range(2)
            ]
            db.add_all(users)
            await db.flush()
            tokens = [secrets.token_urlsafe(32) for _ in users]
            for user, token in zip(users, tokens, strict=True):
                db.add(
                    AuthSession(
                        user_id=user.id,
                        token_hash=token_digest(token),
                        expires_at=now + timedelta(hours=1),
                    )
                )
            conversation = Session(owner_id=users[0].id, title="Smoke")
            db.add(conversation)
            await db.flush()
            run = Run(session_id=conversation.id, query="Smoke")
            db.add(run)
            await db.commit()
        headers = [
            {"Authorization": f"Bearer {token}", "X-API-Token": settings.api_token}
            for token in tokens
        ]
        keyword_settings = settings.model_copy(
            update={
                "embedding_api_key": "",
                "embedding_base_url": "",
                "rerank_enabled": False,
            }
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://smoke"
        ) as client:
            response = await client.post(
                "/ingest",
                headers=headers[0],
                json={
                    "title": "灰度发布回滚手册",
                    "source": "https://example.com/smoke",
                    "content": "# 灰度发布回滚\n灰度发布异常时，先暂停发布，再将流量切回稳定版本，"
                    "然后核对错误率和延迟。回滚负责人需保留变更记录。",
                },
            )
            require(response.status_code == 201, "文档入库失败")
            result = response.json()
            require(result["chunks"] > 0, "未产生片段")
            if settings.has_embedding:
                require(result["embedded"] > 0, "配置的 Embedding 未产生向量")
            print(
                f"[ OK ] 入库：{result['chunks']} 个片段，{result['embedded']} 个向量", flush=True
            )
            query = "请依据知识库说明灰度发布异常时如何回滚，引用原文。"
            hits = await hybrid_search(query, settings=keyword_settings, owner_id=str(users[0].id))
            require(bool(hits), "中文关键词检索未命中")
            require(
                not await hybrid_search(
                    query, settings=keyword_settings, owner_id=str(users[1].id)
                ),
                "跨账号检索泄漏",
            )
            require(
                not await hybrid_search(
                    "zzunmatched9481", settings=keyword_settings, owner_id=str(users[0].id)
                ),
                "无命中查询结果不为空",
            )
            print("[ OK ] 中文关键词、无命中与检索归属", flush=True)
            events = []

            async def emit(event):
                events.append(event)
                await _persist_run_result(str(run.id), settings, event)

            await asyncio.wait_for(
                GraphRunner(settings).run(str(run.id), query, emit, user_id=str(users[0].id)),
                timeout=240,
            )
            done = next((event for event in reversed(events) if event.type == "done"), None)
            require(done is not None, "图运行未完成")
            citations = done.payload.get("citations", [])
            require(bool(citations), "图回答未产生引用")
            require(done.payload.get("retrieval", {}).get("status") == "hit", "诊断不是命中")
            citation = next(
                (
                    item
                    for item in citations
                    if f"[{item['citation_id']}]" in done.payload.get("answer", "")
                ),
                None,
            )
            require(citation is not None, "模型回答未保留实际引用标识")
            path = f"/documents/{citation['document_id']}/chunks/{citation['citation_id']}"
            preview = await client.get(path, headers=headers[0])
            require(
                preview.status_code == 200 and "暂停发布" in preview.json()["content"],
                "原文读取失败",
            )
            require(
                (await client.get(path, headers=headers[1])).status_code == 404, "跨账号原文泄漏"
            )
            snapshots = (
                await client.get(f"/sessions/{conversation.id}/runs", headers=headers[0])
            ).json()
            require(
                snapshots[0]["citations"] == citations
                and snapshots[0]["retrieval"]["status"] == "hit",
                "刷新恢复失败",
            )
            print("[ OK ] 真实图/模型回答、UUID 引用、原文预览与刷新恢复", flush=True)

            # Use the real Postgres checkpointer with an offline model for deterministic HITL.
            ticket_settings = keyword_settings.model_copy(update={"llm_api_key": ""})
            async with factory() as db:
                writes = [
                    Run(session_id=conversation.id, query="创建工单：灰度发布回滚")
                    for _ in range(2)
                ]
                db.add_all(writes)
                await db.commit()
            ticket_events = []

            async def ticket_emit(event):
                ticket_events.append(event)

            calls = [{"name": "create_ticket", "args": {"title": "Smoke ticket"}}]
            ticket_runner = GraphRunner(ticket_settings)
            for write in writes:
                await ticket_runner.run(
                    str(write.id), write.query, ticket_emit, calls, user_id=str(users[0].id)
                )
                require(await ticket_runner.awaiting_approval(str(write.id)), "未等待建单审批")
            async with factory() as db:
                require(
                    await db.scalar(select(func.count()).select_from(Ticket)) == 0,
                    "未确认已创建工单",
                )
            await close_graphs()
            ticket_runner = GraphRunner(ticket_settings)
            require(
                await ticket_runner.awaiting_approval(str(writes[0].id)), "检查点重启后审批丢失"
            )
            await ticket_runner.resume(
                str(writes[0].id), {"ok": False}, ticket_emit, user_id=str(users[0].id)
            )
            async with factory() as db:
                require(
                    await db.scalar(select(func.count()).select_from(Ticket)) == 0, "拒绝建单仍落库"
                )
            await ticket_runner.resume(
                str(writes[1].id), {"ok": True}, ticket_emit, user_id=str(users[0].id)
            )
            require(
                any(
                    event.type == "tool_result" and event.payload.get("ok")
                    for event in ticket_events
                ),
                "批准后建单失败",
            )
            await close_graphs()
            await GraphRunner(ticket_settings).resume(
                str(writes[1].id), {"ok": True}, ticket_emit, user_id=str(users[0].id)
            )
            async with factory() as db:
                require(
                    await db.scalar(select(func.count()).select_from(Ticket)) == 1,
                    "重启或重复恢复产生重复工单",
                )
            print("[ OK ] 真实检查点：未确认、拒绝、批准、重启与重复恢复", flush=True)

            async def create():
                async with factory() as db:
                    ticket = await persist_ticket(
                        db,
                        owner_id=users[0].id,
                        run_id=writes[1].id,
                        fields=TicketFields(title="Smoke ticket"),
                        idempotency_key=f"{writes[1].id}:write:0",
                    )
                    return ticket.id

            ids = await asyncio.gather(create(), create())
            require(ids[0] == ids[1], "并发建单未幂等")
            require(
                (await client.get("/tickets", headers=headers[1])).json()["total"] == 0,
                "跨账号工单泄漏",
            )
            require(
                (
                    await client.patch(
                        f"/tickets/{ids[0]}",
                        headers=headers[0],
                        json={
                            "title": "Edited smoke",
                            "detail": "",
                            "severity": "P1",
                            "status": "resolved",
                        },
                    )
                ).status_code
                == 200,
                "编辑工单失败",
            )
            require(
                (await client.delete(f"/tickets/{ids[0]}", headers=headers[0])).status_code == 200,
                "归档工单失败",
            )
            require(
                (await client.get("/tickets", headers=headers[0])).json()["total"] == 0,
                "归档记录仍在列表",
            )
            try:
                await create()
            except ValueError:
                pass
            else:
                raise AssertionError("重试重新激活了归档工单")
            async with factory() as db:
                require((await db.scalar(select(Ticket))).archived_at is not None, "未软删除")
                legacy_run = await db.get(Run, run.id)
                legacy_run.tool_results = [
                    {
                        "name": "create_ticket",
                        "ok": True,
                        "output": {"ticket_id": "OPS-legacy-smoke", "title": "Legacy"},
                    },
                    {
                        "name": "create_ticket",
                        "ok": True,
                        "output": {"ticket_id": "OPS-conflict", "title": "First"},
                    },
                    {
                        "name": "create_ticket",
                        "ok": True,
                        "output": {"ticket_id": "OPS-conflict", "title": "Different"},
                    },
                ]
                await db.commit()
                conn = await db.connection()
                report = await conn.run_sync(backfill_tickets)
                require(report["imported"] == 1 and report["conflicts"] == 1, "历史回填结果不符")
                await db.commit()
                conn = await db.connection()
                require(
                    (await conn.run_sync(backfill_tickets))["existing"] == 1, "重复历史回填未幂等"
                )
            print("[ OK ] Postgres 并发幂等、编辑、归档、历史回填与用户隔离", flush=True)
    finally:
        await close_graphs()
        await db_runtime.dispose_engine()


def main() -> int:
    settings = Settings().model_copy(
        update={
            "agent_mode": "graph",
            "mcp_mode": "inprocess",
            "redis_url": "",
            "langfuse_public_key": "",
            "langfuse_secret_key": "",
        }
    )
    if not settings.has_database or not settings.has_llm:
        print("[FAIL] 真实冒烟需要 DATABASE_URL 与 LLM 配置")
        return 1
    # Identifier is generated here, never read from a document or user input.
    schema = f"agentops_smoke_{uuid.uuid4().hex}"
    url = make_url(settings.database_url).set(drivername="postgresql+psycopg")
    # Neon pooler rejects startup search_path; direct endpoint keeps isolation explicit.
    if url.host and url.host.endswith(".neon.tech"):
        url = url.set(host=url.host.replace("-pooler.", "."))
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 20})
    created = False
    try:
        with engine.begin() as conn:
            require(
                bool(conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))),
                "数据库尚未启用 pgvector",
            )
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            # Keep Alembic from reading an existing public.alembic_version.
            conn.execute(
                text(
                    f'CREATE TABLE "{schema}".alembic_version '
                    "(version_num varchar(32) NOT NULL PRIMARY KEY)"
                )
            )
            created = True
        scoped_url = (
            url.set(drivername="postgresql")
            .update_query_dict(
                {
                    "options": f"-csearch_path={schema},public",
                }
            )
            .render_as_string(hide_password=False)
        )
        config = Config("alembic.ini")
        config.attributes["database_url"] = scoped_url
        command.upgrade(config, "head")
        scoped_engine = create_engine(
            make_url(scoped_url).set(drivername="postgresql+psycopg"), poolclass=NullPool
        )
        try:
            with scoped_engine.connect() as conn:
                require(
                    conn.scalar(text("SELECT current_schema()")) == schema,
                    "迁移连接未使用隔离 schema",
                )
                require(
                    bool(
                        conn.scalar(
                            text(
                                "SELECT 1 FROM information_schema.columns "
                                "WHERE table_schema=:schema AND table_name='runs' "
                                "AND column_name='retrieval'"
                            ),
                            {"schema": schema},
                        )
                    ),
                    "隔离迁移没有建立 retrieval 列",
                )
        finally:
            scoped_engine.dispose()
        print("[ OK ] 隔离 schema 迁移到 head", flush=True)
        settings = settings.model_copy(update={"database_url": scoped_url})
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(verify(settings, schema))
        return 0
    except Exception as exc:  # noqa: BLE001 - avoid leaking connection strings or API keys
        print(f"[FAIL] {type(exc).__name__}；请检查最后一个已完成阶段（不输出凭据）")
        if isinstance(exc, AssertionError):
            print(f"[FAIL] {exc}")
        original = getattr(exc, "orig", None)
        if original is not None:
            print(f"[FAIL] SQLSTATE={getattr(original, 'sqlstate', None)}")
        return 1
    finally:
        if created:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            print("[ OK ] 已清理隔离测试 schema", flush=True)
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
