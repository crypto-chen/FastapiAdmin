"""客户账龄：从金蝶《应收款账龄分析表》取客户 × 账龄分档金额（CUS-24~27）。

口径（2026-10-14 已确认，见方案 §4.4）：

- 账龄基准 = 到期日 ``FEndDate``（缺失退化业务日期 ``FDate``）
- 净额（应收 − 预收）≤ 0 的客户不纳入
- 剔除内部往来单位编码 100~113
- 账龄截止日 = 期间末日（``FByDate``），历史月份可回补

实现与 ``scripts/ar_aging_check.py`` 同一套取数与分档逻辑（财务已用该脚本对账），
差别只是这里按客户输出、供客户分析宽表使用。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.modules.erp.kingdee.client import KingdeeClient
from app.modules.metadata.sync import _get_sys_report_data_with_retry

logger = logging.getLogger(__name__)

AGING_FORM_ID = "AR_AgingAnalysis"
AGING_FIELD_KEYS = (
    "FContactUnitNumber,FCONTACTUNIT,FBillNo,FDate,FEndDate,"
    "FBalanceAmt,FBalanceAmtFor,FCurrencyName,FMasterCurrencyName,FSettleOrgName,FSaleOrgName,"
    "FSaleDeptName,FSalerName,FBillTypeName"
)
# 报表账龄分组（顺序不能改：FSection/FDays 与 FEntAgingGrpSetting 一一对应）
AGING_SECTIONS: list[dict[str, Any]] = [
    {"FSection": "0-30", "FDays": 30},
    {"FSection": "31-60", "FDays": 60},
    {"FSection": "61-90", "FDays": 90},
    {"FSection": "91-180", "FDays": 180},
    {"FSection": "181-365", "FDays": 365},
    {"FSection": "365以上", "FDays": 0},
]
# 分档：≤max_days 命中该档，None 为兜底档
BUCKETS: list[tuple[int | None, str]] = [
    (30, "0-30"),
    (60, "31-60"),
    (90, "61-90"),
    (180, "91-180"),
    (365, "181-365"),
    (None, ">365"),
]
# CUS 编码 → 报表档位（CUS-27 = 91-180 + 181-365 + >365）
CUS_BUCKET_MAP: dict[str, tuple[str, ...]] = {
    "CUS-24": ("0-30",),
    "CUS-25": ("31-60",),
    "CUS-26": ("61-90",),
    "CUS-27": ("91-180", "181-365", ">365"),
}
INTERNAL_CODES = {str(code) for code in range(100, 114)}
PAGE_SIZE = 2000


def _to_date(value: Any) -> date | None:
    if not value or value in ("-", ""):
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def bucket_index(days: int) -> int:
    for index, (max_days, _label) in enumerate(BUCKETS):
        if max_days is None or days <= max_days:
            return index
    return len(BUCKETS) - 1


def aging_params(by_date: str, settle_org_id: str = "") -> dict[str, Any]:
    return {
        "FieldKeys": AGING_FIELD_KEYS,
        "SchemeId": "",
        "StartRow": 0,
        "Limit": PAGE_SIZE,
        "IsVerifyBaseDataField": "true",
        "FilterString": [],
        "Model": {
            "FAffiliation": {"FNAME": ""},
            "FOutSettle": "false",
            "FAccountSystem": {"FNumber": ""},
            "FSettleOrgLst": settle_org_id,
            "FIsFromFilter": "false",
            "FInSettle": "false",
            "FByDate": by_date,
            "FByBill": "true",
            "FUnAudit": "false",
            "FIncludePayEvaluate_New": "false",
            "FOnlyShowPayEvaluate_New": "false",
            "FShowSumLocal": "false",
            "FShowLocal": "false",
            "FGroupCustomer": "false",
            "FToEndDate": "false",
            "FNoPreReceive": "false",
            "FOnlyShowPreReceive": "false",
            "FCONTACTUNITMUL": "",
            "FMULCONTACT": "false",
            "FEXCLUDEB2CAR": "false",
            "FReSetAllocateExc": "false",
            "FExChangeRateType": {"FNUMBER": "HLTX01_SYS"},
            "FAgingCalStd": "0",
            "FEntAgingGrpSetting": AGING_SECTIONS,
        },
    }


async def fetch_aging_rows(
    client: KingdeeClient, by_date: str, settle_org_id: str = ""
) -> list[list]:
    """按单据分页取全量（单据编号为空的是客户小计行，调用方需跳过）。"""
    rows: list[list] = []
    start = 0
    while True:
        params = aging_params(by_date, settle_org_id)
        params["StartRow"] = start
        result = await _get_sys_report_data_with_retry(client, AGING_FORM_ID, params)
        inner = result.get("Result") or result
        if not inner.get("IsSuccess", True):
            message = str((inner.get("ResponseStatus") or {}).get("Errors", [{}])[0].get("Message", ""))
            raise RuntimeError(f"账龄分析表取数失败: {message}")
        page = inner.get("Rows") or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += len(page)
    return rows


def aggregate_by_customer(rows: list[list], as_of: date) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """明细行 → ``{客户编码: {CUS-24..27, name, total}}`` + 各档合计。"""
    grouped: dict[str, dict[str, Any]] = {}
    for raw in rows:
        code, name, bill_no, bill_date, end_date, balance_local = (list(raw) + [None] * 6)[:6]
        if not bill_no:  # 「xxx(小计)」行
            continue
        code_text = str(code or "").strip()
        if code_text in INTERNAL_CODES:
            continue
        base = _to_date(end_date) or _to_date(bill_date)
        if base is None:
            continue
        item = grouped.setdefault(
            code_text or str(name or ""), {"name": str(name or ""), "amounts": [0.0] * len(BUCKETS)}
        )
        item["amounts"][bucket_index((as_of - base).days)] += _amount(balance_local)

    result: dict[str, dict[str, Any]] = {}
    bucket_totals = {label: 0.0 for _max, label in BUCKETS}
    for code, item in grouped.items():
        net = round(sum(item["amounts"]), 4)
        if net <= 0:  # 净额 ≤ 0 的客户不纳入
            continue
        values = {label: round(item["amounts"][i], 4) for i, (_max, label) in enumerate(BUCKETS)}
        record: dict[str, Any] = {"name": item["name"], "total": net}
        for cus_code, labels in CUS_BUCKET_MAP.items():
            record[cus_code] = round(sum(values[label] for label in labels), 4)
        result[code] = record
        for label, value in values.items():
            bucket_totals[label] += value
    return result, bucket_totals
