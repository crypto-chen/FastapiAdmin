#!/bin/bash
# 回滚「零售售后/退货退款同步」（2026-10-27）
#
# 作用：
#   1. alembic downgrade -1：删除 retail_after_sale_item / retail_after_sale，版本回到 retailshop01
#   2. 可选 git revert：把代码回退到上一个提交
#
# 用法：
#   bash deploy/retail-aftersale-20261027/ROLLBACK.sh                 # 只降数据库（代码保留）
#   bash deploy/retail-aftersale-20261027/ROLLBACK.sh --with-code     # 降库 + git revert 本次提交
#   ENVIRONMENT=dev bash deploy/retail-aftersale-20261027/ROLLBACK.sh # 指定环境，默认 prod
#
# 不影响 retail_order / retail_order_item / retail_shop / retail_sync_batch。
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

echo "[2/3] 回滚一个迁移（删除两张售后表）："
"$PYTHON_BIN" -m alembic -c alembic.ini downgrade -1

echo "[3/3] 回滚后版本："
"$PYTHON_BIN" -m alembic -c alembic.ini current || true

cd "$WORK_DIR"
if [ "${1:-}" = "--with-code" ]; then
  echo "回退代码（git revert 最近一个提交）："
  git revert --no-edit HEAD
fi

echo "回滚完成。定时任务随代码回滚自动取消；如只降库，重启后端后售后页签会提示接口不存在。"
