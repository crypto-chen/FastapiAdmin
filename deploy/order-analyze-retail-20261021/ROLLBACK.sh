#!/bin/bash
# 回滚 CRM orderAnalyze type=3（零售）本次变更。
# 注意：会删除本次上线后创建的宽表/指标新版本，只保留历史版本。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "[1/3] 恢复代码"
for rel in \
  backend/app/modules/order/build.py \
  backend/app/modules/order/fields.py \
  backend/app/modules/order/schedule.py \
  backend/app/modules/customer/build.py \
  backend/app/modules/product/fields.py \
  backend/scripts/seed_order_module.py \
  backend/scripts/seed_crm_person_metrics.py; do
  if [ -f "deploy/order-analyze-retail-20261021/baseline/$rel" ]; then
    cp "deploy/order-analyze-retail-20261021/baseline/$rel" "$rel"
    echo "  恢复 $rel"
  fi
done

echo "[2/3] 回滚数据库（删除本次新版本、type=3 批次、恢复指标定义）"
cd "$ROOT/backend"
python ../deploy/order-analyze-retail-20261021/rollback_retail.py --since "${SINCE:-2026-10-21 09:50:00}"

echo "[3/3] 重启后端"
if [ -n "${SERVICE:-}" ]; then
  systemctl restart "$SERVICE"
  systemctl status "$SERVICE" --no-pager | head -5
else
  echo "  未指定 SERVICE：请按现有方式重启后端进程"
fi

echo "回滚完成。"
