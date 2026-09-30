"""初始化数据库：执行版本化迁移并启用 pgvector 扩展。

用法：
    uv run python scripts/init_db.py
"""

from __future__ import annotations

from alembic.config import Config

from alembic import command
from src.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.has_database:
        print("[FAIL] 未配置 DATABASE_URL，请先在 .env 中填写 Neon 连接串")
        return 1
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    print("[ OK ] 已启用 pgvector 扩展并完成数据库迁移")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
