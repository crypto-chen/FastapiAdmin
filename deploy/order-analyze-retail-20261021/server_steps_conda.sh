#!/bin/bash
# CRM orderAnalyze type=3（零售）服务器更新步骤（conda Python，默认预演）
#
# 在服务器项目根目录执行：
#   bash deploy/order-analyze-retail-20261021/server_steps_conda.sh --dry-run
#   bash deploy/order-analyze-retail-20261021/server_steps_conda.sh --apply
#
# 覆盖变量：
#   ENV=prod                     读取 backend/env/.env.prod
#   SYNC_PERIODS=...             零售订单同步期间
#   BUILD_PERIODS=...            订单/客户/产品线重建期间
#   METRIC_PERIOD_FROM/TO=...    指标重算期间
#   SERVICE=fastapiadmin         systemd 服务名（可选）
set -euo pipefail

APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --service) shift; SERVICE="${1:-}" ;;
    -h|--help) echo "用法: $0 [--apply|--dry-run] [--service 服务名]"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/backend"
ENV_NAME="${ENV:-prod}"
SERVICE="${SERVICE:-}"
SYNC_PERIODS="${SYNC_PERIODS:-2023-11,2023-12,2024-01,2024-02,2024-03,2024-04,2024-05,2024-06,2024-07,2024-08,2024-09,2024-10,2024-11,2024-12,2025-01,2025-02,2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10}"
BUILD_PERIODS="${BUILD_PERIODS:-2024-10,2024-11,2024-12,2025-01,2025-02,2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10}"
RETAIL_PERIODS="${RETAIL_PERIODS:-2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10}"
METRIC_PERIOD_FROM="${METRIC_PERIOD_FROM:-2025-07}"
METRIC_PERIOD_TO="${METRIC_PERIOD_TO:-2026-10}"
PY="${PYTHON:-python}"

run() {
  echo "  \$ $*"
  if [ "$APPLY" -eq 1 ]; then
    (cd "$BACKEND" && ENVIRONMENT="$ENV_NAME" "$@")
  fi
}

echo "项目根目录：$ROOT"
echo "后端环境：$ENV_NAME"
echo "解释器：$PY"
echo "模式：$([ "$APPLY" -eq 1 ] && echo '执行' || echo '预演')"
echo

echo "[1/8] 指标/来源对象定义（新增零售来源对象与业务员指标口径）"
run "$PY" scripts/seed_crm_person_metrics.py
run "$PY" scripts/seed_order_module.py

echo "[2/8] 同步零售订单 type=3（2023-11 ~ 2026-10）"
run "$PY" scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（零售）" --period "$SYNC_PERIODS"

echo "[3/8] 重建订单全链路（2024-10 ~ 2026-10）"
run "$PY" scripts/run_order_build.py --period "$BUILD_PERIODS"

echo "[4/8] 重建客户分析（零售有数据的期间）"
run "$PY" scripts/run_customer_build.py --period "$RETAIL_PERIODS"

echo "[5/8] 重建产品线分析（零售有数据的期间）"
run "$PY" scripts/run_product_build.py --period "$RETAIL_PERIODS"

echo "[6/8] 重算业务员指标及下游（含费用分摊/人均/结算收益）"
run "$PY" scripts/recalc_metrics_batch.py --code-file scripts/metric_groups/order_retail.txt \
  --with-dependents --period-from "$METRIC_PERIOD_FROM" --period-to "$METRIC_PERIOD_TO"

echo "[7/8] 校验"
run "$PY" scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（零售）" --period 2026-09 --show-latest
run "$PY" scripts/verify_ord01_formula.py --period 2026-09 || true

echo "[8/8] 重启后端"
if [ -n "$SERVICE" ]; then
  if [ "$APPLY" -eq 1 ]; then
    systemctl restart "$SERVICE"
    systemctl status "$SERVICE" --no-pager | head -5
  else
    echo "  \$ systemctl restart $SERVICE"
  fi
else
  echo "  未指定 --service：请按现有方式重启后端进程（systemd/screen/nohup）"
fi

echo
if [ "$APPLY" -eq 1 ]; then
  echo "服务器更新完成。"
else
  echo "预演完成，未执行任何命令。确认后加 --apply。"
fi
