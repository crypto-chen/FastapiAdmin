#!/usr/bin/env bash
# 回滚运营中心口径对齐（文件层）：恢复指标引擎、指标定义脚本与测试。
# 用法: bash deploy/opcenter-align-20261111/ROLLBACK.sh [仓库根目录]
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:-$(cd "$HERE/../.." && pwd)}"

cp "$HERE/baseline/engine.py" "$ROOT/backend/app/modules/metric/engine.py"
cp "$HERE/baseline/seed_opcenter_metrics.py" "$ROOT/backend/scripts/seed_opcenter_metrics.py"
cp "$HERE/baseline/test_opcenter_dept_filter.py" "$ROOT/backend/tests/test_opcenter_dept_filter.py"

echo "rollback done: $ROOT"
