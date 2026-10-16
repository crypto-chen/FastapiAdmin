#!/bin/bash
# 产品线分析：服务器端部署步骤（默认预演，加 --apply 才执行）
#
# 前置：代码已上传并解包（deploy/product-line/upload.sh --apply）
# 用法：bash deploy/product-line/server_steps.sh --dry-run
#       bash deploy/product-line/server_steps.sh --apply
set -euo pipefail

APPLY=0
PERIODS="${PERIODS:-2026-07,2026-08,2026-09}"
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    -h|--help) echo "用法: $0 [--apply|--dry-run]（期间用环境变量 PERIODS 覆盖，默认 ${PERIODS}）"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKER_DIR="$ROOT/docker"
cd "$ROOT"

run() {
  echo "  \$ $*"
  # 注意用 if 而非 && ：set -e 下 `[ ] && cmd` 在预演时会返回 1 直接终止脚本
  if [ "$APPLY" -eq 1 ]; then
    "$@"
  fi
}

echo "仓库根目录：$ROOT"
echo "模式：$([ "$APPLY" -eq 1 ] && echo '执行' || echo '预演')"
echo

echo "[1/7] 备份数据库（务必先确认 .env 里的 MYSQL_ROOT_PASSWORD 可读）"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T mysql mysqldump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --single-transaction --databases fastapiadmin > /root/fastapiadmin_backup_\$(date +%Y%m%d_%H%M).sql"

echo "[2/7] 重建并启动后端（启动时自动 alembic upgrade head）"
run bash -c "cd '$DOCKER_DIR' && docker compose build backend && docker compose up -d --force-recreate backend"

echo "[3/7] 校验迁移"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T mysql mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" fastapiadmin -e \"SELECT version_num FROM alembic_version; SHOW TABLES LIKE 'dwd_product_line%'; SHOW COLUMNS FROM open_client LIKE 'allow_product_line_detail';\""

echo "[4/7] 建来源对象与同步任务（CRM 发货明细）"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T backend python scripts/seed_crm_shipment_detail.py"

echo "[5/7] 建标准实体 / 字段 / 菜单 / 角色授权"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T backend python scripts/seed_product_module.py"

echo "[6/7] 回补数据（期间 ${PERIODS}）：发货明细取数 → 订单全链路 → 产品线宽表"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T backend python scripts/run_meta_sync.py --name 'CRM发货明细-getShipmentsDetail' --period ${PERIODS} --show-latest"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T backend python scripts/run_order_build.py --period ${PERIODS}"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T backend python scripts/run_product_build.py --period ${PERIODS}"

echo "[7/7] 生成外部对接文档（按实际对外域名替换 --base-url）"
run bash -c "cd '$DOCKER_DIR' && docker compose exec -T backend python scripts/gen_product_line_api_doc.py --base-url 'https://<对外域名>' --period 2026-09"
echo "  取回本地：docker compose cp backend:/app/docs/产品线指标开放接口对接说明.md ./"

echo
if [ "$APPLY" -eq 1 ]; then
  echo "部署步骤执行完毕。记得：① 前端 dist 已更新；② 给对接方开 allow_product_line_detail。"
else
  echo "预演完成，未执行任何命令。确认无误后加 --apply 重跑。"
fi
