#!/usr/bin/env bash
set -euo pipefail

# 回滚 PUSH-01-a / PUSH-01-b 取数接口调整。
# 用法：
#   bash deploy/push-type-20261020/ROLLBACK.sh
#   ROLLBACK_REF=<commit> bash deploy/push-type-20261020/ROLLBACK.sh

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

REF="${ROLLBACK_REF:-HEAD^}"
FILES=(
  backend/scripts/seed_crm_push_metrics.py
  backend/scripts/crm_check.py
  backend/app/modules/crm/client.py
  backend/app/modules/metadata/sync.py
  docs/核算指标系统设计.md
)

echo "回滚代码到 $REF"
git checkout "$REF" -- "${FILES[@]}"
rm -f backend/tests/test_crm_push_amount_sources.py

echo "代码已回滚。"
echo "数据库定义回滚：在 backend 目录重新执行旧版 seed 脚本；或参考 backend/artifacts/push_type_20261020/before.json。"
