"""按客户输出《应收款账龄分析表》的账龄分档金额（供 CUS-24~27 核对，只读不写库）。

口径与已确认的账龄口径一致：净额（应收 − 预收）≤ 0 的客户不纳入、账龄基准 = 到期日 `FEndDate`、
剔除内部往来单位 100~113、账龄截止日 = 指定期末日。取数逻辑直接复用 ``ar_aging_check.py``。

用法：
    python scripts/customer_aging_sample.py --as-of 2026-09-30 --top 12
    python scripts/customer_aging_sample.py --as-of 2026-09-30 --org 101 --top 12
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (str(PROJECT_ROOT), str(SCRIPT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ar_aging_check import _fetch_aging_rows, _org_id_map  # noqa: E402
from kingdee_report_probe import AGING_FIELD_KEYS  # noqa: E402

from app.modules.erp.kingdee.client import KingdeeClient  # noqa: E402

INI_PATH = PROJECT_ROOT / "env" / "kindee_conf.ini"
INTERNAL_CODES = {str(code) for code in range(100, 114)}
BUCKETS: list[str] = ["账龄30天", "账龄60天", "账龄90天", "账龄90天以上"]


def to_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_date(value) -> date | None:
    if not value or value in ("-", ""):
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def bucket_of(days: int) -> str:
    if days <= 30:
        return "账龄30天"
    if days <= 60:
        return "账龄60天"
    if days <= 90:
        return "账龄90天"
    return "账龄90天以上"


async def main() -> None:
    parser = argparse.ArgumentParser(description="客户账龄分档抽样")
    parser.add_argument("--as-of", default="2026-09-30", help="账龄截止日 YYYY-MM-DD")
    parser.add_argument("--org", default="", help="结算组织编码，缺省全部组织")
    parser.add_argument("--top", type=int, default=12, help="输出前 N 个客户")
    args = parser.parse_args()

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    client = KingdeeClient.from_ini(INI_PATH)
    org_id = ""
    if args.org:
        org_id = (await _org_id_map(client)).get(args.org, "")
        if not org_id:
            raise SystemExit(f"未取到组织 {args.org} 的内码")

    keys = [key.strip() for key in AGING_FIELD_KEYS.split(",")]
    rows = await _fetch_aging_rows(client, org_id, args.as_of, "FEndDate")
    if not rows:
        raise SystemExit("未取到账龄数据")

    customers: dict[str, dict] = defaultdict(lambda: {"name": "", **dict.fromkeys(BUCKETS, 0.0)})
    skipped_internal = 0
    skipped_subtotal = 0
    for raw in rows:
        row = raw if isinstance(raw, dict) else dict(zip(keys, raw, strict=False))
        code = str(row.get("FContactUnitNumber") or "").strip()
        if not str(row.get("FBillNo") or "").strip():
            skipped_subtotal += 1
            continue
        if not code:
            continue
        if code in INTERNAL_CODES:
            skipped_internal += 1
            continue
        amount = to_number(row.get("FBalanceAmt"))
        if not amount:
            continue
        based = parse_date(row.get("FEndDate")) or parse_date(row.get("FDate"))
        if based is None:
            continue
        item = customers[code]
        item["name"] = str(row.get("FCONTACTUNIT") or item["name"]).strip()
        item[bucket_of((as_of - based).days)] += amount

    valid = {code: item for code, item in customers.items() if sum(item[b] for b in BUCKETS) > 0}
    excluded = len(customers) - len(valid)

    print(
        f"截止日 {args.as_of}｜组织 {args.org or '全部'}(内码 {org_id or '-'})｜明细行 {len(rows)}"
        f"｜小计行 {skipped_subtotal}｜剔除内部行 {skipped_internal}｜净额≤0 排除客户 {excluded}"
        f"｜有效客户 {len(valid)}"
    )
    print(
        f"\n{'客户编码':<20}{'客户名称':<26}{'账龄30天':>15}{'账龄60天':>15}"
        f"{'账龄90天':>15}{'90天以上':>16}{'合计':>16}"
    )
    top = sorted(valid.items(), key=lambda kv: -sum(kv[1][b] for b in BUCKETS))[: args.top]
    for code, item in top:
        values = [item[b] for b in BUCKETS]
        print(
            f"{code:<20}{item['name'][:24]:<26}{values[0]:>15,.2f}{values[1]:>15,.2f}"
            f"{values[2]:>15,.2f}{values[3]:>16,.2f}{sum(values):>16,.2f}"
        )
    grand = {b: sum(item[b] for item in valid.values()) for b in BUCKETS}
    print(
        f"{'合计':<20}{'':<26}{grand['账龄30天']:>15,.2f}{grand['账龄60天']:>15,.2f}"
        f"{grand['账龄90天']:>15,.2f}{grand['账龄90天以上']:>16,.2f}{sum(grand.values()):>16,.2f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
