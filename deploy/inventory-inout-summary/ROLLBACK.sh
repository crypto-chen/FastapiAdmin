#!/bin/bash
# 回滚「存货收发存汇总表（全仓·全物料）」数据接入（幂等）：删除数据源、标准实体、字段映射与同步任务。
#
# 用法：
#   bash deploy/inventory-inout-summary/ROLLBACK.sh                 # 回滚默认库（env/.env.dev 的 DATABASE_NAME）
#   bash deploy/inventory-inout-summary/ROLLBACK.sh <数据库名>       # 回滚指定库（例如副本库上先验证一遍）
#
# 回滚范围（按业务键匹配，与运行次数无关）：
#   meta_sync_run → meta_sync_job → meta_field_mapping → meta_source_field
#   → meta_standard_field → meta_standard_entity → meta_source_object
# 不影响既有的「存货收发存汇总表-组织100」（仓库区间 JXCPC）数据源与依赖它的指标。
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

cd backend
if [ "$#" -gt 0 ]; then
  "$PYTHON_BIN" scripts/seed_inventory_inout_summary_full.py --rollback --db-name "$1"
else
  "$PYTHON_BIN" scripts/seed_inventory_inout_summary_full.py --rollback
fi
