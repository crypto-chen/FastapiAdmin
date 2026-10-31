#!/usr/bin/env bash
# 回滚客户编码匹配改造：恢复上一提交代码，并用旧口径重跑宽表与指标。
# 用法：bash deploy/customer-code-20261031/ROLLBACK.sh [commit]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

TARGET="${1:-HEAD}"
echo "回滚提交：$TARGET"
git revert --no-edit "$TARGET"

cd "$ROOT/backend"

PERIODS="2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10"

python scripts/seed_crm_person_metrics.py
python scripts/run_order_build.py --period "$PERIODS"
python scripts/run_customer_build.py --period "$PERIODS"
python scripts/recalc_metrics_batch.py \
  --code marketing_person_new_customer_intake_untaxed \
  --code marketing_person_old_customer_intake_untaxed \
  --code marketing_person_old_customer_order_count \
  --code marketing_person_total_customer_count \
  --with-dependents \
  --period-from 2025-07 --period-to 2026-10

echo "回滚完成：请按现有方式重启后端进程"
