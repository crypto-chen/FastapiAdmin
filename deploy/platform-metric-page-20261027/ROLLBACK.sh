#!/bin/bash
# 回滚「指标中心 → 平台分析」页面（2026-10-27）
#
# 作用：
#   1. 删除「平台分析」菜单、子按钮及角色绑定（幂等）
#   2. 可选 git revert 回退代码
#
# 用法：
#   bash deploy/platform-metric-page-20261027/ROLLBACK.sh
#   bash deploy/platform-metric-page-20261027/ROLLBACK.sh --with-code
set -euo pipefail
WORK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORK_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x "backend/.venv/bin/python" ]; then PYTHON_BIN="backend/.venv/bin/python"
  elif [ -x "backend/.venv/Scripts/python.exe" ]; then PYTHON_BIN="backend/.venv/Scripts/python.exe"
  else PYTHON_BIN="python"; fi
fi
ENVIRONMENT="${ENVIRONMENT:-prod}"
export ENVIRONMENT

echo "[1/2] 删除平台分析菜单与角色绑定："
"$PYTHON_BIN" deploy/platform-metric-page-20261027/rollback_menu.py

if [ "${1:-}" = "--with-code" ]; then
  echo "[2/2] 回退代码："
  git revert --no-edit HEAD
else
  echo "[2/2] 代码保留；页面菜单已移除，重启后端后左侧不再显示「指标中心 → 平台分析」。"
fi
