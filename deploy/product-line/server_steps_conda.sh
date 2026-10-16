#!/bin/bash
# 产品线分析：服务器端部署步骤（conda / 非 Docker 版，默认预演，加 --apply 才执行）
#
# 前置：
#   1. 代码已拉取/上传到服务器项目目录（git pull origin master）
#   2. 依赖已装进 conda 环境（首次或依赖有变化时跑 --install-deps）
#   3. backend/env/.env.prod 已存在且数据库连接可用
#
# 用法：
#   bash deploy/product-line/server_steps_conda.sh --dry-run
#   bash deploy/product-line/server_steps_conda.sh --apply
#   bash deploy/product-line/server_steps_conda.sh --apply --conda-env fastapiadmin
#   PERIODS=2025-01,2025-02,2026-09 bash deploy/product-line/server_steps_conda.sh --apply
#
# 可覆盖的环境变量：
#   PERIODS     回补期间，默认 2026-07,2026-08,2026-09
#   ENV         后端环境名，默认 prod（读取 backend/env/.env.prod）
#   ENV_FILE    环境文件路径，默认 backend/env/.env.$ENV
#   CONDA_ENV   conda 环境名（给了就用 conda run -n 执行，否则用当前已激活环境的 python）
#   PYTHON      显式指定解释器（优先级高于 CONDA_ENV）
#   SERVICE     systemd 服务名（给了就 systemctl restart，否则只打印重启提示）
set -euo pipefail

APPLY=0
INSTALL_DEPS=0
PERIODS="${PERIODS:-2026-07,2026-08,2026-09}"
ENV_NAME="${ENV:-prod}"
CONDA_ENV="${CONDA_ENV:-}"
SERVICE="${SERVICE:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --install-deps) INSTALL_DEPS=1 ;;
    --conda-env) shift; CONDA_ENV="${1:-}" ;;
    --service) shift; SERVICE="${1:-}" ;;
    --periods) shift; PERIODS="${1:-}" ;;
    -h|--help)
      echo "用法: $0 [--apply|--dry-run] [--install-deps] [--conda-env <名称>] [--service <systemd服务名>] [--periods 2026-07,2026-08]"
      exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/backend"
ENV_FILE="${ENV_FILE:-$BACKEND/env/.env.$ENV_NAME}"

if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -n "$CONDA_ENV" ]; then
  if command -v conda >/dev/null 2>&1; then
    PY="conda run --no-capture-output -n $CONDA_ENV python"
  else
    echo "错误：找不到 conda，但指定了 --conda-env" >&2; exit 3
  fi
else
  PY="python"
fi

run() {
  echo "  \$ $*"
  if [ "$APPLY" -eq 1 ]; then "$@"; fi
}

run_shell() {
  echo "  \$ $*"
  if [ "$APPLY" -eq 1 ]; then bash -c "$*"; fi
}

env_get() {
  # 从 .env.prod 读键值（允许 "KEY = value" 写法与行尾注释）
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*([^#]*).*/\1/p" "$2" | head -1 | sed -E 's/[[:space:]]+$//'
}

echo "仓库根目录：$ROOT"
echo "后端环境：$ENV_NAME（$ENV_FILE）"
echo "解释器：$PY"
echo "回补期间：$PERIODS"
echo "模式：$([ "$APPLY" -eq 1 ] && echo '执行' || echo '预演')"
echo

if [ ! -d "$BACKEND" ]; then
  echo "错误：找不到 backend 目录：$BACKEND" >&2
  exit 3
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "警告：环境文件不存在：$ENV_FILE" >&2
  echo "      请参照 backend/env/.env.example 创建，至少填写 ENVIRONMENT / SECRET_KEY / DATABASE_* / REDIS_*" >&2
fi

echo "[1/7] 备份数据库"
if [ -f "$ENV_FILE" ]; then
  DB_HOST="$(env_get DATABASE_HOST "$ENV_FILE")"
  DB_PORT="$(env_get DATABASE_PORT "$ENV_FILE")"
  DB_USER="$(env_get DATABASE_USER "$ENV_FILE")"
  DB_PASSWORD="$(env_get DATABASE_PASSWORD "$ENV_FILE")"
  DB_NAME="$(env_get DATABASE_NAME "$ENV_FILE")"
  DB_HOST="${DB_HOST:-localhost}"; DB_PORT="${DB_PORT:-3306}"
  DB_NAME="${DB_NAME:-fastapiadmin}"
  if [ -z "$DB_PASSWORD" ]; then
    echo "  跳过：.env.$ENV_NAME 里没读到 DATABASE_PASSWORD（请确认后再手工备份）"
  else
    run_shell "mysqldump -h'$DB_HOST' -P'$DB_PORT' -u'$DB_USER' -p'$DB_PASSWORD' --single-transaction --databases '$DB_NAME' > /root/fastapiadmin_backup_\$(date +%Y%m%d_%H%M).sql && ls -lh /root/fastapiadmin_backup_*.sql | tail -1"
  fi
else
  echo "  跳过（环境文件缺失）"
fi

echo "[2/7] 依赖（仅 --install-deps 时执行；kingdee SDK 走本地 wheel，须在 backend 目录下装）"
if [ "$INSTALL_DEPS" -eq 1 ]; then
  run_shell "cd '$BACKEND' && $PY -m pip install -U pip && $PY -m pip install -r requirements.txt"
else
  echo "  跳过（加 --install-deps 才装；首次部署或 requirements.txt 有变化时要加）"
fi

echo "[3/7] 数据库迁移（alembic upgrade head，期望 head = 27578c7b66b6）"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY main.py upgrade --env=$ENV_NAME"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY -m alembic current"

echo "[4/7] 建来源对象与同步任务（CRM 发货明细）"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY scripts/seed_crm_shipment_detail.py"

echo "[5/7] 建标准实体 / 字段 / 菜单 / 角色授权"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY scripts/seed_product_module.py"

echo "[6/7] 回补数据（期间 $PERIODS）：发货明细取数 → 订单全链路 → 产品线宽表"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY scripts/run_meta_sync.py --name 'CRM发货明细-getShipmentsDetail' --period $PERIODS --show-latest"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY scripts/run_order_build.py --period $PERIODS"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY scripts/run_product_build.py --period $PERIODS"

echo "[7/7] 生成外部对接文档"
run_shell "cd '$BACKEND' && ENVIRONMENT='$ENV_NAME' $PY scripts/gen_product_line_api_doc.py --base-url 'https://<对外域名>' --period 2026-09"

echo
echo "[重启后端] 新增同步任务必须重启一次进程，调度器才会挂上"
if [ -n "$SERVICE" ]; then
  run_shell "systemctl restart '$SERVICE' && systemctl status '$SERVICE' --no-pager | head -5"
else
  echo "  未指定 --service：请手工重启你的后端进程（systemd / supervisor / screen / nohup 均可）"
  echo "  例：systemctl restart fastapiadmin"
  echo "  例：cd '$BACKEND' && ENVIRONMENT=$ENV_NAME nohup $PY main.py run --env=$ENV_NAME > logs/run.log 2>&1 &"
fi

echo
if [ "$APPLY" -eq 1 ]; then
  echo "部署步骤执行完毕。别忘了：① 前端已 npm run build 并发布；② 给对接方开 allow_product_line_detail。"
else
  echo "预演完成，未执行任何命令。确认无误后加 --apply 重跑。"
fi
