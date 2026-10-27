#!/bin/bash
# 回滚「平台渠道分析指标开放接口」（2026-10-27）
#
# 作用：
#   1. alembic downgrade -1：删除 open_client.allow_platform_analysis（版本回到 b0f396df56ac）
#   2. 可选 git revert：把代码回退到上一个提交
#
# 用法：
#   bash deploy/platform-analysis-api-20261027/ROLLBACK.sh              # 只降库（代码保留）
#   bash deploy/platform-analysis-api-20261027/ROLLBACK.sh --with-code  # 降库 + git revert
#   ENVIRONMENT=dev bash deploy/platform-analysis-api-20261027/ROLLBACK.sh
#
# 不影响 retail_order / retail_after_sale / 已开通的其他开放接口权限。
set -euo pipefail

WORK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORK_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x "backend/.venv/bin/python" ]; then
    PYTHON_BIN="backend/.venv/bin/python"
  elif [ -x "backend/.venv/Scripts/python.exe" ]; then
    PYTHON_BIN="backend/.venv/Scripts/python.exe"
  else
    PYTHON_BIN="python"
  fi
fi

ENVIRONMENT="${ENVIRONMENT:-prod}"
export ENVIRONMENT

cd backend
echo "[1/3] 当前迁移版本："
"$PYTHON_BIN" -m alembic -c alembic.ini current || true

echo "[2/3] 回滚一个迁移（删除 allow_platform_analysis）："
"$PYTHON_BIN" -m alembic -c alembic.ini downgrade -1

echo "[3/3] 回滚后版本："
"$PYTHON_BIN" -m alembic -c alembic.ini current || true

cd "$WORK_DIR"
if [ "${1:-}" = "--with-code" ]; then
  echo "回退代码（git revert 最近一个提交）："
  git revert --no-edit HEAD
fi

echo "回滚完成。重启后端后，/open/v1/retail/platform/analysis 对所有应用返回 403。"
