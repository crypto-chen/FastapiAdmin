#!/usr/bin/env bash
set -euo pipefail

# STF-18 / STF-30 折算比例 10% -> 18%
# 用法：
#   bash deploy/stf30-rate-20261020/deploy.sh --dry-run
#   bash deploy/stf30-rate-20261020/deploy.sh --apply
#   bash deploy/stf30-rate-20261020/deploy.sh --check
#   bash deploy/stf30-rate-20261020/deploy.sh --rollback

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "backend/.venv/bin/python" ]]; then
  PY="backend/.venv/bin/python"
elif [[ -x "backend/.venv/Scripts/python.exe" ]]; then
  PY="backend/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

echo "使用 Python: $PY"
exec "$PY" backend/scripts/deploy_stf30_rate.py "$@"
