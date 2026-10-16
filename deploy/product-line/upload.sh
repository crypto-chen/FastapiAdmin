#!/bin/bash
# 产品线分析：把本次改动的文件打包并上传到服务器（默认只打包 + 预演，加 --apply 才真正上传）
#
# 用法：
#   bash deploy/product-line/upload.sh --host root@1.2.3.4 --dest /path/to/FastapiAdmin
#   bash deploy/product-line/upload.sh --host root@1.2.3.4 --dest /path/to/FastapiAdmin --apply
#
# 上传后在服务器上执行 deploy/product-line/server_steps.sh 完成部署。
set -euo pipefail

HOST=""
DEST=""
APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --host) shift; HOST="${1:-}" ;;
    --dest) shift; DEST="${1:-}" ;;
    -h|--help)
      echo "用法: $0 --host <user@server> --dest <服务器项目目录> [--apply]"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "$HOST" ] || [ -z "$DEST" ]; then
  echo "错误：必须提供 --host 与 --dest" >&2
  echo "示例：bash deploy/product-line/upload.sh --host root@1.2.3.4 --dest /www/FastapiAdmin --apply" >&2
  exit 2
fi

WORK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M)"
BUNDLE="product-line_${STAMP}.tar.gz"

FILES=(
  backend/app/modules/product
  backend/app/modules/order/model.py
  backend/app/modules/order/build.py
  backend/app/modules/openapi/model.py
  backend/app/modules/openapi/schema.py
  backend/app/api/v1/routers.py
  backend/app/api/open/v1/routers.py
  backend/app/alembic/versions/2026_10_16_1505_a34e992661d6.py
  backend/app/alembic/versions/2026_10_16_1526_e2d66304120f.py
  backend/app/alembic/versions/2026_10_16_1530_27578c7b66b6.py
  backend/scripts/seed_crm_shipment_detail.py
  backend/scripts/seed_product_module.py
  backend/scripts/run_product_build.py
  backend/scripts/gen_product_line_api_doc.py
  frontend/web/src/api/module_product
  frontend/web/src/views/module_metric/product
  frontend/web/src/views/module_openapi/client/index.vue
  frontend/web/src/api/module_openapi/index.ts
  docs/营销中心产品线分析报表方案.md
  docs/产品线上线部署说明.md
  docs/产品线指标开放接口对接说明.md
  deploy/product-line/server_steps_conda.sh
  CHANGELOG.md
)

cd "$WORK_DIR"
echo "仓库根目录：$WORK_DIR"
echo "目标：$HOST:$DEST"
echo "打包文件数：${#FILES[@]}"

missing=()
for f in "${FILES[@]}"; do [ -e "$f" ] || missing+=("$f"); done
if [ ${#missing[@]} -gt 0 ]; then
  echo "错误：以下路径不存在：" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 3
fi

tar -czf "/tmp/${BUNDLE}" --exclude='__pycache__' "${FILES[@]}"
echo "已打包：/tmp/${BUNDLE}（$(du -h "/tmp/${BUNDLE}" | cut -f1)）"

if [ "$APPLY" -ne 1 ]; then
  echo "预演完成，未上传。确认无误后加 --apply 重跑。"
  exit 0
fi

  scp "/tmp/${BUNDLE}" "${HOST}:/tmp/"
  ssh "$HOST" "cd '${DEST}' && tar -xzf /tmp/${BUNDLE} && echo '解包完成' && bash deploy/product-line/server_steps.sh --dry-run"
echo "上传完成。在服务器上执行：cd ${DEST} && bash deploy/product-line/server_steps.sh --apply"
