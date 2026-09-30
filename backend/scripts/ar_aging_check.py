"""应收账龄 / 坏账计提直连校验（不依赖数据库）。

两种取数口径都支持，用于和业务手上的《应收款账龄分析表》对表：

- ``--source aging``（默认）：金蝶《应收款账龄分析表》``AR_AgingAnalysis`` 按单据的
  「尚未收款金额（本位币）」+ 业务日期/到期日——与指标 ``marketing_bad_debt_provision`` 同口径。
- ``--source receivable``：应收单 ``AR_receivable`` 的未收款金额 ``FNoReceiveAmount``——交叉验证用。

计提规则：0-30 天 0%、31-60 天 5%、61-90 天 10%、91-180 天 20%、181-365 天 50%、1 年以上 100%；
默认剔除编码 100-113 的内部客户（``--keep-internal`` 可关闭）；
默认按往来单位取净值、**净额为负的客户不纳入计提**（``--netting bill`` 改为逐单计提）。

用法：
    python scripts/ar_aging_check.py --org-code 101
    python scripts/ar_aging_check.py --org-code 101 --as-of 2026-09-30
    python scripts/ar_aging_check.py --basis FDate                 # 按业务日期计提
    python scripts/ar_aging_check.py --netting bill                # 逐单计提（原口径）
    python scripts/ar_aging_check.py --source receivable
    python scripts/ar_aging_check.py --source aging --all-orgs     # 全部组织（不带组织过滤）
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INI = PROJECT_ROOT / "env" / "kindee_conf.ini"
for path in (str(PROJECT_ROOT), str(SCRIPT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.modules.erp.kingdee.client import KingdeeBillQueryRequest, KingdeeClient  # noqa: E402
from app.modules.metadata.sync import _get_sys_report_data_with_retry  # noqa: E402
from kingdee_report_probe import AGING_FIELD_KEYS, aging_params  # noqa: E402

RECEIVABLE_FIELD_KEYS = (
    "FBillNo,FDate,FENDDATE_H,FCustomerID.FNumber,FCustomerID.FName,"
    "FNoReceiveAmount,FSETTLEORGID.FNumber,FCURRENCYID.FNumber,FDOCUMENTSTATUS,FCancelStatus"
)

# 计提规则：账龄天数 ≤ max_days 的档位比例（None = 兜底档）
BUCKETS = [
    (30, 0.0),
    (60, 0.05),
    (90, 0.10),
    (180, 0.20),
    (365, 0.50),
    (None, 1.0),
]
INTERNAL_CUSTOMERS = {str(code) for code in range(100, 114)}


def _to_date(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _amount(value: object) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _bucket_index(days: int) -> int:
    for index, (max_days, _rate) in enumerate(BUCKETS):
        if max_days is None or days <= max_days:
            return index
    return len(BUCKETS) - 1


def _bucket_label(index: int) -> str:
    max_days = BUCKETS[index][0]
    previous = BUCKETS[index - 1][0] if index else None
    if max_days is None:
        return f">{previous}" if previous is not None else "全部"
    return f"{0 if previous is None else previous + 1}-{max_days}"


async def _org_id_map(client: KingdeeClient) -> dict[str, str]:
    """组织编码 → 组织内码（账龄分析表 FSettleOrgLst 要内码）。"""
    _fields, items = await client.bill_query(
        KingdeeBillQueryRequest(form_id="ORG_Organizations", field_keys="FNumber,FOrgID", limit=200)
    )
    return {str(item.get("FNumber")): str(item.get("FOrgID")) for item in items if item.get("FOrgID")}


async def _fetch_aging_rows(client: KingdeeClient, org_id: str, by_date: str, basis: str) -> list[list]:
    """《应收款账龄分析表》按单据取全量（FSettleOrgLst 传组织内码）。"""
    field_keys = AGING_FIELD_KEYS
    rows: list[list] = []
    start = 0
    while True:
        params = aging_params(org_id or "", by_date, field_keys)
        params["Model"].update(
            {
                "FAgingCalStd": "0",
                "FExChangeRateType": {"FNUMBER": "HLTX01_SYS"},
                "FByBill": "true",
                "FEntAgingGrpSetting": [
                    {"FSection": _bucket_label(i), "FDays": BUCKETS[i][0] or 0}
                    for i in range(len(BUCKETS))
                ],
            }
        )
        params["StartRow"] = start
        params["Limit"] = 2000
        result = await _get_sys_report_data_with_retry(client, "AR_AgingAnalysis", params)
        inner = result.get("Result") or result
        if not inner.get("IsSuccess"):
            message = str((inner.get("ResponseStatus") or {}).get("Errors", [{}])[0].get("Message", ""))
            raise SystemExit(f"账龄分析表取数失败: {message}")
        page = inner.get("Rows") or []
        rows.extend(page)
        if len(page) < 2000:
            break
        start += len(page)
    return rows


async def _fetch_receivable_rows(client: KingdeeClient, org_code: str) -> list[dict]:
    """应收单未收款金额（按结算组织过滤，分页取全量）。"""
    conditions = ["FDocumentStatus='C'", "FCancelStatus='A'", "FNoReceiveAmount<>0"]
    if org_code:
        conditions.append(f"FSETTLEORGID.FNumber='{org_code}'")
    rows: list[dict] = []
    start = 0
    while True:
        _fields, page = await client.bill_query(
            KingdeeBillQueryRequest(
                form_id="AR_receivable",
                field_keys=RECEIVABLE_FIELD_KEYS,
                filter_string=" and ".join(conditions),
                order_string="FDate asc",
                start_row=start,
                limit=2000,
            )
        )
        rows.extend(page)
        if len(page) < 2000:
            break
        start += len(page)
    return rows


def _normalize(source: str, rows: list, basis: str) -> list[tuple[str, str, date, float]]:
    """统一成 ``(客户编码, 客户名称, 账龄基准日, 金额)``。"""
    result: list[tuple[str, str, date, float]] = []
    if source == "aging":
        for row in rows:
            code, name, bill_no, bill_date, end_date, balance_local, _balance_for = (list(row) + [None] * 7)[:7]
            if not bill_no:  # 「xxx(小计)」行
                continue
            base = _to_date(end_date if basis == "FEndDate" else bill_date) or _to_date(bill_date)
            if base is None:
                continue
            result.append((str(code or ""), str(name or ""), base, _amount(balance_local)))
        return result
    for row in rows:
        base = _to_date(row.get("FENDDATE_H" if basis == "FEndDate" else "FDate")) or _to_date(row.get("FDate"))
        if base is None:
            continue
        result.append(
            (
                str(row.get("FCustomerID.FNumber") or ""),
                str(row.get("FCustomerID.FName") or ""),
                base,
                _amount(row.get("FNoReceiveAmount")),
            )
        )
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="应收账龄/坏账计提直连校验")
    parser.add_argument("--ini", default=str(DEFAULT_INI), help="金蝶 conf.ini 路径")
    parser.add_argument("--source", default="aging", choices=["aging", "receivable"], help="取数口径")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="账龄截止日 YYYY-MM-DD")
    parser.add_argument("--basis", default="FEndDate", choices=["FEndDate", "FDate"], help="账龄基准字段")
    parser.add_argument("--org-code", default="101", help="组织编码（账龄分析表会换算成组织内码）")
    parser.add_argument("--all-orgs", action="store_true", help="不带组织过滤（账龄分析表会取 0 行，仅调试用）")
    parser.add_argument("--keep-internal", action="store_true", help="不剔除内部客户 100-113")
    parser.add_argument(
        "--netting", default="customer", choices=["customer", "bill"], help="计提口径：客户净值（默认）/ 逐单"
    )
    parser.add_argument("--top", type=int, default=10, help="计提金额前 N 个客户")
    args = parser.parse_args()

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    client = KingdeeClient.from_ini(args.ini)

    if args.source == "aging":
        org_id = "" if args.all_orgs else (await _org_id_map(client)).get(args.org_code, "")
        if not args.all_orgs and not org_id:
            raise SystemExit(f"未取到组织 {args.org_code} 的组织内码")
        raw_rows = await _fetch_aging_rows(client, org_id, args.as_of, args.basis)
        print(f"《应收款账龄分析表》组织 {args.org_code}(内码 {org_id or '-'}) 取到 {len(raw_rows)} 行")
    else:
        raw_rows = await _fetch_receivable_rows(client, "" if args.all_orgs else args.org_code)
        print(f"应收单（未收款金额）取到 {len(raw_rows)} 行")

    rows = _normalize(args.source, raw_rows, args.basis)
    bucket_amount = Counter()
    bucket_provision = Counter()
    bucket_rows = Counter()
    by_customer: dict[str, dict] = {}
    total_amount = 0.0
    provision = 0.0
    skipped_internal = 0
    excluded_customers = 0

    if args.netting == "customer":
        # 客户层净值：先按客户汇总各档净额，净额 ≤ 0 的客户整体不计提
        grouped: dict[str, dict] = {}
        for code, name, base, amount in rows:
            if not args.keep_internal and code in INTERNAL_CUSTOMERS:
                skipped_internal += 1
                continue
            index = _bucket_index((as_of - base).days)
            item = grouped.setdefault(code or name, {"name": name, "amounts": [0.0] * len(BUCKETS)})
            item["amounts"][index] += amount
        for code, item in grouped.items():
            net_amount = round(sum(item["amounts"]), 4)
            if net_amount <= 0:
                excluded_customers += 1
                continue
            item_provision = round(
                sum(item["amounts"][i] * BUCKETS[i][1] for i in range(len(BUCKETS))), 4
            )
            total_amount += net_amount
            provision += item_provision
            by_customer[code] = {"name": item["name"], "amount": net_amount, "provision": item_provision}
            for index in range(len(BUCKETS)):
                label = _bucket_label(index)
                bucket_amount[label] += item["amounts"][index]
                bucket_provision[label] += item["amounts"][index] * BUCKETS[index][1]
                if item["amounts"][index]:
                    bucket_rows[label] += 1

    if args.netting != "customer":
        # 逐单计提：每张单据按自身账龄档位计提
        for code, name, base, amount in rows:
            if not args.keep_internal and code in INTERNAL_CUSTOMERS:
                skipped_internal += 1
                continue
            days = (as_of - base).days
            index = _bucket_index(days)
            rate = BUCKETS[index][1]
            label = _bucket_label(index)
            bucket_amount[label] += amount
            bucket_provision[label] += amount * rate
            bucket_rows[label] += 1
            total_amount += amount
            provision += amount * rate
            item = by_customer.setdefault(
                code or name, {"name": name, "amount": 0.0, "provision": 0.0}
            )
            item["amount"] += amount
            item["provision"] += amount * rate

    print(
        f"账龄截止日 {as_of}，账龄基准 {args.basis}，计提口径 {args.netting}，"
        f"剔除内部客户行 {skipped_internal}，净额为负被排除客户 {excluded_customers}"
    )
    print(f"尚未收款合计 {total_amount:,.2f}，计提合计 {provision:,.2f}，客户数 {len(by_customer)}")
    print("分档：")
    for index in range(len(BUCKETS)):
        label = _bucket_label(index)
        print(
            f"  {label:<9} 比例 {BUCKETS[index][1] * 100:>5.0f}%  行数 {bucket_rows[label]:<6}"
            f" 金额 {bucket_amount[label]:>18,.2f}  计提 {bucket_provision[label]:>16,.2f}"
        )
    print(f"计提金额前 {args.top} 客户：")
    for code, item in sorted(by_customer.items(), key=lambda kv: -abs(kv[1]["provision"]))[: args.top]:
        print(
            f"  {code:<20} {str(item['name'])[:18]:<20} 余额 {item['amount']:>14,.2f}"
            f" 计提 {item['provision']:>14,.2f}"
        )
    print(json.dumps({"as_of": str(as_of), "total": round(total_amount, 2), "provision": round(provision, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
