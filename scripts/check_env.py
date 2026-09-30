"""环境自检：逐项检查并给出可复制的修复建议。

用法：
    uv run python scripts/check_env.py
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import sys
from pathlib import Path

OK = "[ OK ]"
WARN = "[WARN]"
FAIL = "[FAIL]"


def _print(status: str, name: str, detail: str = "") -> None:
    line = f"{status} {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 12)
    _print(
        OK if ok else FAIL,
        "Python 版本",
        f"{major}.{minor}（要求 >=3.12）" if ok else f"{major}.{minor}，请安装 Python 3.12",
    )
    return ok


def check_tool(name: str, hint: str) -> bool:
    path = shutil.which(name)
    if path:
        _print(OK, f"{name} 可用", path)
        return True
    _print(WARN, f"{name} 未找到", hint)
    return False


def check_env_file() -> bool:
    root = Path(__file__).resolve().parents[1]
    exists = (root / ".env").exists()
    if exists:
        _print(OK, ".env 已创建")
    else:
        _print(WARN, ".env 不存在", "复制 .env.example 为 .env 并填入密钥")
    return exists


async def check_database() -> bool:
    from src.config import get_settings
    from src.db.session import get_engine

    settings = get_settings()
    if not settings.has_database:
        _print(WARN, "DATABASE_URL 未配置", "先用 Neon 免费实例，RAG 与检查点需要 Postgres")
        return False
    try:
        engine = get_engine(settings)
        if engine is None:
            return False
        from sqlalchemy import text

        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version()"))).scalar_one()
            has_vector = (await conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            ))).scalar_one()
    except Exception as exc:  # noqa: BLE001 - 自检脚本需捕获所有连接异常
        _print(FAIL, "Postgres 连接失败", str(exc)[:160])
        return False
    _print(OK, "Postgres 连通", str(version)[:60])
    if has_vector:
        _print(OK, "pgvector 扩展已启用")
        return True
    _print(WARN, "pgvector 未启用", "运行 python scripts/init_db.py")
    return False


async def check_llm() -> bool:
    from src.config import get_settings

    settings = get_settings()
    if not settings.has_llm:
        _print(WARN, "LLM_API_KEY 未配置", "编排将使用 EchoLLM 离线兜底，仅用于跑通链路")
        return False
    try:
        import httpx
    except ImportError:
        _print(WARN, "httpx 未安装", "先执行 uv sync")
        return False

    url = f"{settings.llm_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, "模型服务不可达", str(exc)[:160])
        return False
    if response.status_code == 200:
        _print(OK, "模型服务连通", f"{settings.llm_base_url} / {settings.llm_model}")
        return True
    _print(FAIL, "模型服务返回异常", f"HTTP {response.status_code}: {response.text[:120]}")
    return False


async def main() -> int:
    print(f"AgentOps 环境自检（{platform.system()} {platform.release()}）")
    print("-" * 72)
    results = [check_python()]
    results.append(check_tool("uv", "winget install astral-sh.uv"))
    results.append(check_tool("node", "前端需要 Node 22+"))
    results.append(check_tool("pnpm", "npm i -g pnpm"))
    if check_tool("docker", "可选：本地 docker compose 演示；Railway 部署不需要") is False:
        results.append(True)  # Docker 为可选项，不影响通过
    results.append(check_env_file())
    results.append(await check_database())
    results.append(await check_llm())

    print("-" * 72)
    blocking = results[:1] + results[5:]
    if all(blocking):
        print("结论：核心环境就绪（Python / 数据库 / 模型）")
        return 0
    print("结论：存在未通过项，按上方建议修复后重跑本脚本")
    return 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(asyncio.run(main()))
