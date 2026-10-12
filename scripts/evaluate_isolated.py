"""Evaluate in a temporary schema of the existing Postgres database, then remove test data.

--storage-check validates migrations/publication without model calls or publishing to public.
Evaluation is offline unless --with-model explicitly enables configured paid services.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from evals import runner
from src.agent.graph import close_graphs
from src.config import Settings
from src.db import session as db_runtime
from src.db.eval_reports import latest_report, publish_report
from src.db.models import Document, EvalRun, Run, Session, Ticket, User
from src.eval_report import CompletedEvalReport
from src.rag.ingest import ingest_document


def evaluation_settings(settings: Settings, with_model: bool) -> Settings:
    updates = {"app_env": "staging", "agent_mode": "graph", "redis_url": ""}
    if not with_model:
        updates.update(llm_api_key="", embedding_api_key="", rerank_api_key="",
                       rerank_enabled=False)
    return settings.model_copy(update=updates)


def isolated_url(settings: Settings, schema: str):
    if not re.fullmatch(r"agentops_eval_[0-9a-f]{32}", schema):
        raise ValueError("Only generated evaluation schemas are allowed")
    url = make_url(settings.database_url).set(drivername="postgresql")
    if url.host and url.host.endswith(".neon.tech"):
        url = url.set(host=url.host.replace("-pooler.", "."))
    return url.update_query_dict({"options": f"-csearch_path={schema}"})


@contextmanager
def database_scope(settings: Settings):
    schema = f"agentops_eval_{uuid.uuid4().hex}"
    scoped = isolated_url(settings, schema)
    base_url = scoped.difference_update_query(["options"]).set(drivername="postgresql+psycopg")
    engine = create_engine(base_url, poolclass=NullPool, connect_args={"connect_timeout": 20})
    created = False
    try:
        with engine.begin() as conn:
            if not conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname='vector'")):
                raise ValueError("The existing database must already have pgvector installed")
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'CREATE TABLE "{schema}".alembic_version '
                              '(version_num varchar(32) PRIMARY KEY)'))
            created = True
        # Migrations need public for pgvector types; runtime checkpoint queries do not.
        migration_url = scoped.update_query_dict({"options": f"-csearch_path={schema},public"})
        config = Config("alembic.ini")
        config.attributes["database_url"] = migration_url.render_as_string(hide_password=False)
        command.upgrade(config, "head")
        print("[ OK ] Temporary evaluation schema migrated to head", flush=True)
        yield settings.model_copy(update={
            "database_url": scoped.render_as_string(hide_password=False),
        }), schema
    finally:
        if created:
            # `schema` is generated and verified above, never supplied by a document or operator.
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            print("[ OK ] Temporary evaluation schema removed", flush=True)
        engine.dispose()


async def verify_storage(factory):
    """Synthetic summaries exercise storage only and never become a published product report."""
    now = datetime.now(UTC)
    emails = [f"storage-{i}@eval.invalid" for i in range(2)]
    async with factory() as db:
        db.add_all([User(email=email, display_name="Evaluation", password_hash="unused",
                         role="admin", verified_at=now) for email in emails])
        db.add(EvalRun(metrics={"task_success_rate": 99}))  # Legacy rows remain invisible.
        await db.commit()
    report = CompletedEvalReport.model_validate({
        "schema_version": 1, "id": uuid.uuid4(), "status": "completed",
        "started_at": now, "generated_at": now + timedelta(seconds=1), "git_sha": "a" * 40,
        "prompt_version": "storage-test", "model_version": "offline", "selected_cases": 1,
        "source": {
            "environment": "staging", "golden_set_version": "storage-test",
            "code_dirty": False, "cheap_model": "offline", "llm_configured": False,
            "database_configured": True, "embedding_configured": False,
            "rerank_configured": False, "configured_retrieval_mode": "bm25",
            "tool_data_source": "sample",
            "agent_flags": {"mode": "graph", "routing": False, "retry": False, "dynamic": False},
        },
        "metrics": {
            "cases": 1, "citation_skipped": 0, "task_success_rate": 0, "tool_accuracy": 0,
            "recall_at_5": None, "p50_latency_ms": 100, "p95_latency_ms": 100,
            "avg_tokens": None, "cost_per_task": None, "failure_stages": {"retrieve": 1},
        },
    })

    async def send(email):
        async with factory() as db:
            return await publish_report(db, report, email)

    assert sorted(await asyncio.gather(*(send(email) for email in emails))) == [False, True]
    async with factory() as db:
        assert await publish_report(db, report, emails[0]) is False
    async with factory() as db:
        latest = await latest_report(db)
        assert latest.id == report.id and latest.generated_at == report.generated_at
        assert latest.metrics["cost_per_task"] is None
        changed = report.model_copy(update={"prompt_version": "conflicting-content"})
        try:
            await publish_report(db, changed, emails[0])
        except ValueError:
            pass
        else:
            raise AssertionError("Conflicting content must not replace a report")
        for model in (Document, Run, Session, Ticket):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
    print("[ OK ] Postgres migration, publication, idempotence, conflict and isolation", flush=True)


async def evaluate(settings: Settings, schema: str, args):
    url = make_url(settings.database_url).set(drivername="postgresql+asyncpg")
    if "sslmode" in url.query:
        url = url.update_query_dict({"ssl": url.query["sslmode"]})
    url = url.difference_update_query(["sslmode", "channel_binding", "options"])
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 20})

    @event.listens_for(engine.sync_engine, "connect")
    def use_schema(connection, _record):
        async def configure(raw):
            await raw.execute(f'SET search_path TO "{schema}", public')
            if await raw.fetchval("SELECT current_schema()") != schema:
                raise RuntimeError("Evaluation database isolation failed")
        connection.run_async(configure)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    original_engine, original_factory = db_runtime._engine, db_runtime._session_factory
    db_runtime._engine, db_runtime._session_factory = engine, factory
    try:
        if args.storage_check:
            await verify_storage(factory)
            return 0
        async with factory() as db:
            user = User(email="runner@eval.invalid", display_name="Evaluation",
                        password_hash="unused", verified_at=datetime.now(UTC))
            db.add(user)
            await db.commit()
            user_id = str(user.id)
        await ingest_document(
            title="评测测试文档", source="evaluation-fixture", version="eval-fixture-v1",
            content=("订单服务出现 5xx、下单超时或支付服务 p99 延迟升高时，先检查服务错误率、"
                     "数据库连接池及慢查询，结合代码定位原因。数据库连接池打满可限制并发并排查连接泄漏。"
                     "发布回滚需要审核确认，创建工单须得到人工批准。生产指标应以实际监控为准。"),
            settings=settings, owner_id=user.id,
        )
        return await runner.main(args.limit, args.offset, user_id, "staging", settings=settings)
    finally:
        await close_graphs()
        db_runtime._engine, db_runtime._session_factory = original_engine, original_factory
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--storage-check", action="store_true")
    parser.add_argument("--with-model", action="store_true", help="Enable configured paid services")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    settings = evaluation_settings(Settings(_env_file=args.env_file), args.with_model)
    if not settings.has_database:
        print("[FAIL] DATABASE_URL is required")
        return 1
    try:
        with database_scope(settings) as (scoped, schema):
            return runner._run(evaluate(scoped, schema, args))
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}; isolated evaluation failed (credentials omitted)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
