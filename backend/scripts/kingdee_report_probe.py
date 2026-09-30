"""本地调试：探测金蝶报表/查询对象的 FormId 与字段名（只读，不落库）。

金蝶 ``GetSysReportData`` / ``ExecuteBillQuery`` 都不会校验字段名：
字段写错不报错，只返回空值，所以字段名只能靠「试 + 看有没有值」反查。
本脚本支持：

1. 逐个体尝候选 FormId，确认报表对象是否存在；
2. 一次传多个候选字段名，打印每列非空数量与样本，定位真实字段名；
3. ``QueryBusinessInfo`` 查看业务对象信息（名称、支持的操作）。

用法：
    python scripts/kingdee_report_probe.py
    python scripts/kingdee_report_probe.py --form-id AR_AgingAnalysis --fields FBillNo,FCustomerID
    python scripts/kingdee_report_probe.py --form-id AR_AgingAnalysis --business-info
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = PROJECT_ROOT / "env" / "kindee_conf.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.erp.kingdee.client import KingdeeClient  # noqa: E402

# 候选报表 FormId：应收款账龄分析表相关命名（金蝶报表 FormId 常见为 <模块>_RPT_<名称>）
CANDIDATE_FORM_IDS = [
    "AR_RPT_AgingAnalysis",
    "AR_RPT_AgeAnalysis",
    "AR_RPT_ReceivableAging",
    "AR_RPT_ReceivableAgingAnalysis",
    "AR_RPT_ARDueAge",
    "AR_RPT_BillAging",
    "AR_RPT_Aging",
    "AR_AgingAnalysis",
    "AR_ReceivableAging",
    "AR_RPT_AgingReport",
]

# 候选字段名：应收款账龄分析表（客户 / 单据 / 日期 / 金额 / 各账龄区间）
CANDIDATE_FIELDS = [
    "FBillNo",
    "FDate",
    "FBillDate",
    "FCustomerID",
    "FCustID",
    "FCustomerId",
    "FCurrencyID",
    "FAmount",
    "FAmountFor",
    "FEndAmount",
    "FBalance",
    "FNotDueAmount",
    "FAge1",
    "FAge2",
    "FAge3",
    "FAge4",
    "FAge5",
    "FAge6",
    "FAmount1",
    "FAmount2",
    "FAmount3",
    "FAmount4",
    "FAmount5",
    "FAmount6",
]

MINIMAL_PARAMS = {"FieldKeys": "FBillNo", "StartRow": 0, "Limit": 5}

# 取数模式：report = GetSysReportData；bill = ExecuteBillQuery。由 main() 按参数覆盖。
MODE = "report"

# 《应收款账龄分析表》(AR_AgingAnalysis) 的 Model 参数（来源：金蝶 WebAPI 文档）
AGING_FIELD_KEYS = (
    "FContactUnitNumber,FCONTACTUNIT,FBillNo,FDate,FEndDate,"
    "FBalanceAmt,FBalanceAmtFor,FCurrencyName,FMasterCurrencyName,FSettleOrgName,FSaleOrgName,"
    "FSaleDeptName,FSalerName,FBillTypeName"
)


def aging_params(org_code: str, by_date: str, field_keys: str = AGING_FIELD_KEYS) -> dict:
    """构造应收款账龄分析表的请求参数。"""
    return {
        "FieldKeys": field_keys,
        "SchemeId": "",
        "StartRow": 0,
        "Limit": 2000,
        "IsVerifyBaseDataField": "true",
        "FilterString": [],
        "Model": {
            "FAffiliation": {"FNAME": ""},
            "FOutSettle": "false",
            "FAccountSystem": {"FNumber": ""},
            "FSettleOrgLst": org_code,
            "FIsFromFilter": "false",
            "FInSettle": "false",
            "FByDate": by_date,
            "FByBill": "false",
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
            "FExChangeRateType": {"FNUMBER": ""},
            "FAgingCalStd": "",
            "FEntAgingGrpSetting": [{"FSection": "", "FDays": 0}],
        },
    }


def _unwrap(result: dict) -> dict:
    """金蝶响应外层是 ``{"Result": {...}}``；单据查询还会再包一层列表。"""
    for _ in range(3):
        if isinstance(result, dict) and isinstance(result.get("Result"), dict):
            result = result["Result"]
            continue
        if isinstance(result, list) and result:
            result = result[0]
            continue
        break
    return result if isinstance(result, dict) else {}


def _dump(path: str, payload: object) -> None:
    """把结果写成 UTF-8 文件，避开 Windows 控制台 GBK 乱码。"""
    if not path:
        return
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 {path}")


def column_stats(rows: list, fields: list[str]) -> None:
    """打印每列的非空数量与首个非空样本，用于反查报表字段名。"""
    for index, field in enumerate(fields):
        samples: list[str] = []
        non_null = 0
        for row in rows:
            if not isinstance(row, list) or index >= len(row):
                continue
            value = row[index]
            if value is None or value == "":
                continue
            non_null += 1
            if len(samples) < 3:
                samples.append(str(value))
        flag = "命中" if non_null else "空列"
        print(f"{flag} {field:<28} 非空 {non_null:<6} 样例 {samples}")


async def probe(client: KingdeeClient, form_id: str, params: dict, out_path: str = "") -> None:
    print(f"\n=== {form_id} ===")
    try:
        result = await client.get_sys_report_data(form_id, params)
    except Exception as e:  # noqa: BLE001 - 探测脚本需要打印全部异常
        print(f"EXC  {e}")
        return
    result = _unwrap(result)
    rows = result.get("Rows")
    if isinstance(rows, list):
        raw_fields = params.get("FieldKeys") or ""
        fields = [item.strip() for item in str(raw_fields).split(",") if item.strip()]
        print(f"IsSuccess={result.get('IsSuccess')} RowCount={result.get('RowCount')} 列数={len(fields)}")
        column_stats(rows, fields)
        _dump(out_path, {"form_id": form_id, "params": params, "result": result})
        return
    text = json.dumps(result, ensure_ascii=False)
    print(text[:2000])


def _missing_field(result: dict) -> str:
    """从金蝶返回里取出「标识为XXX的字段不存在」中的字段名。"""
    result = _unwrap(result)
    status = (result or {}).get("ResponseStatus") or {}
    for error in status.get("Errors") or []:
        message = str(error.get("Message") or "")
        if "字段不存在" not in message:
            continue
        end = message.find("的字段不存在")
        if end < 0:
            end = message.find("字段不存在")
        start = message.find("为") + 1
        if 0 < start < end:
            return message[start:end]
    return ""


async def _fetch(client: KingdeeClient, form_id: str, field_keys: str, mode: str, limit: int) -> dict:
    """按模式取数：``report`` = GetSysReportData，``bill`` = ExecuteBillQuery（原始 JSON）。"""
    if mode == "bill":
        sdk = client._new_sdk()  # noqa: SLF001 - 探测脚本直接调用 SDK
        payload = {"FormId": form_id, "FieldKeys": field_keys, "StartRow": 0, "Limit": limit}
        raw = sdk.ExecuteBillQuery(payload)
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"Result": {"ResponseStatus": {"Errors": [{"Message": str(raw)}]}}}
        if isinstance(parsed, list):
            flat = parsed[0] if parsed and isinstance(parsed[0], list) else parsed
            if flat and isinstance(flat[0], dict):
                return {"Result": flat[0]}  # 单据查询把错误包了一层列表
            return {"Result": {"Rows": parsed, "RowCount": len(parsed), "IsSuccess": True}}
        return {"Result": parsed}
    return await client.get_sys_report_data(form_id, {"FieldKeys": field_keys, "StartRow": 0, "Limit": limit})


async def discover_fields(client: KingdeeClient, form_id: str, candidates: list[str]) -> list[str]:
    """逐个剔除「字段不存在」的候选，剩下的就是该报表的有效字段名。"""
    fields = list(candidates)
    for _ in range(len(candidates) + 5):
        result = await _fetch(client, form_id, ",".join(fields), MODE, 3)
        missing = _missing_field(result)
        if missing:
            print(f"无效字段，剔除：{missing}")
            fields = [field for field in fields if field != missing]
            if not fields:
                return []
            continue
        inner = _unwrap(result)
        rows = inner.get("Rows")
        print(f"有效字段 {len(fields)} 个，RowCount={inner.get('RowCount')}")
        if isinstance(rows, list):
            column_stats(rows, fields)
        return fields
    return fields


async def business_info(client: KingdeeClient, form_id: str) -> None:
    """查询业务对象信息（``QueryBusinessInfo``），用于确认报表字段清单。"""
    print(f"\n=== QueryBusinessInfo {form_id} ===")
    sdk = client._new_sdk()  # noqa: SLF001 - 探测脚本直接调用 SDK
    raw = sdk.QueryBusinessInfo(json.dumps({"FormId": form_id}, ensure_ascii=False))
    print(str(raw)[:4000])


async def main() -> None:
    parser = argparse.ArgumentParser(description="金蝶报表 FormId 探测")
    parser.add_argument("--ini", default=str(DEFAULT_INI), help="金蝶 conf.ini 路径")
    parser.add_argument("--form-id", default="", help="只探测指定 FormId（可重复传入）")
    parser.add_argument("--params-file", default="", help="请求参数 JSON 文件")
    parser.add_argument("--fields", default="", help="逗号分隔的候选字段名")
    parser.add_argument("--out", default="", help="把报表原始返回写成 UTF-8 JSON 文件")
    parser.add_argument("--business-info", action="store_true", help="改查业务对象信息而不是报表数据")
    parser.add_argument("--discover", action="store_true", help="逐个剔除无效候选字段，列出有效字段名")
    parser.add_argument("--mode", default="report", choices=["report", "bill"], help="discover 模式下的取数方式")
    parser.add_argument("--aging", action="store_true", help="按《应收款账龄分析表》参数取数")
    parser.add_argument("--org", default="", help="--aging 时的结算组织编码（必填）")
    parser.add_argument("--by-date", default="", help="--aging 时的截止日期 YYYY-MM-DD（必填）")
    args = parser.parse_args()

    global MODE  # noqa: PLW0603 - 探测脚本用模块级开关复用取数函数
    MODE = args.mode

    params = MINIMAL_PARAMS
    if args.params_file:
        params = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
    elif args.aging:
        params = aging_params(args.org, args.by_date, args.fields or AGING_FIELD_KEYS)
    elif args.fields:
        params = {**MINIMAL_PARAMS, "FieldKeys": args.fields}

    form_ids = [args.form_id] if args.form_id else (["AR_AgingAnalysis"] if args.aging else CANDIDATE_FORM_IDS)
    client = KingdeeClient.from_ini(args.ini)
    for form_id in form_ids:
        if args.business_info:
            await business_info(client, form_id)
        elif args.discover:
            candidates = [item.strip() for item in args.fields.split(",") if item.strip()] or CANDIDATE_FIELDS
            await discover_fields(client, form_id, candidates)
        else:
            await probe(client, form_id, params, args.out)


if __name__ == "__main__":
    asyncio.run(main())
