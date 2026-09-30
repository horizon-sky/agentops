#!/usr/bin/env bash
# AgentOps 一键环境初始化（Windows / Git Bash）
#
# 用法：
#   bash scripts/bootstrap.sh
#
# 说明：脚本只做「检测 + 安装 + 初始化」，不会写入任何密钥；
#       密钥请在 .env 中自行填写。

set -euo pipefail

echo "==> 1/5 检查 Python 3.12（与容器镜像保持一致）"
if ! command -v python >/dev/null 2>&1; then
  winget install --id Python.Python.3.12 --exact \
    --accept-source-agreements --accept-package-agreements --disable-interactivity
  echo "Python 安装完成，请重启终端使 PATH 生效，然后重新运行本脚本"
  exit 0
else
  echo "python 已存在：$(python --version 2>&1)"
  echo "提示：仓库已固定 .python-version=3.12，uv 会优先使用该版本"
fi

echo "==> 2/5 检查并安装 uv"
if ! command -v uv >/dev/null 2>&1; then
  winget install --id astral-sh.uv --exact \
    --accept-source-agreements --accept-package-agreements --disable-interactivity
  echo "uv 安装完成，请重启终端使 PATH 生效，然后重新运行本脚本"
  exit 0
else
  echo "uv 已存在：$(uv --version)"
fi

echo "==> 3/5 安装 Python 依赖"
uv sync --extra dev

echo "==> 4/5 初始化 .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env，请填入 DATABASE_URL / LLM_API_KEY 等配置"
else
  echo ".env 已存在，跳过"
fi

echo "==> 5/5 环境自检"
uv run python scripts/check_env.py || true

echo
echo "下一步："
echo "  1. 编辑 .env，填入 Neon 的 DATABASE_URL 与模型 API Key"
echo "  2. uv run python scripts/init_db.py    # 建表 + 启用 pgvector"
echo "  3. uv run pytest                       # 冒烟测试"
echo "  4. uv run uvicorn apps.api.src.main:app --reload --port 8000"
