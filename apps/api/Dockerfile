# 运行时与本地开发统一使用 Python 3.12（见仓库 .python-version）
# 多阶段构建：依赖层与源码分离，减小最终镜像体积
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

RUN uv venv /opt/venv \
    && UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY apps ./apps
COPY services ./services
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY scripts ./scripts

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

# 非 root 运行
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY pyproject.toml README.md ./
COPY src ./src
COPY apps ./apps
COPY services ./services
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY scripts ./scripts
COPY data ./data

USER appuser

# Railway 注入 PORT；Uvicorn 必须监听 0.0.0.0
CMD ["sh", "-c", "uvicorn apps.api.src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
