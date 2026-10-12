"""金蝶单据查询字段探测（只读，不写库）。

用途：接新单据（如生产订单 ``PRD_MO``）时，先用本脚本确认真实可用的
``FieldKeys`` 与过滤条件，再把确认过的字段写进 seed 脚本，避免同步任务
上线后因字段名不对整批取数为空。

用法：
    python scripts/kingdee_bill_probe.py --form-id PRD_MO --fields FBillNo,FDate
    python scripts/kingdee_bill_probe.py --form-id PRD_MO --filter "FBillNo='MO00123'"
    python scripts/kingdee_bill_probe.py --form-id PRD_MO --fields FBillNo --limit 5 --json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.erp.kingdee.client import (  # noqa: E402
    KingdeeBillQueryRequest,
    KingdeeClient,
)

INI_PATH = PROJECT_ROOT / "env" / "kindee_conf.ini"


async def main() -> None:
    parser = argparse.ArgumentParser(description="金蝶单据查询字段探测")
    parser.add_argument("--form-id", required=True, help="业务对象表单Id，如 PRD_MO")
    parser.add_argument("--fields", default="FBillNo,FDate,FDocumentStatus", help="FieldKeys，逗号分隔")
    parser.add_argument("--filter", dest="filter_string", default="", help="FilterString（金蝶语法）")
    parser.add_argument("--order", dest="order_string", default="", help="OrderString")
    parser.add_argument("--limit", type=int, default=3, help="返回行数（最大 10000）")
    parser.add_argument("--json", action="store_true", help="原样打印 JSON")
    args = parser.parse_args()

    client = KingdeeClient.from_ini(INI_PATH)
    request = KingdeeBillQueryRequest(
        form_id=args.form_id,
        field_keys=args.fields,
        filter_string=args.filter_string,
        order_string=args.order_string,
        top_row_count=0,
        start_row=0,
        limit=args.limit,
    )
    fields, items = await client.bill_query(request)
    print(f"FormId={args.form_id} 字段数={len(fields)} 行数={len(items)}")
    print("返回列: " + ",".join(str(item) for item in fields))
    for index, item in enumerate(items, start=1):
        if args.json:
            print(json.dumps(item, ensure_ascii=False, default=str))
        else:
            print(f"--- 第 {index} 行 ---")
            print(json.dumps(item, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
