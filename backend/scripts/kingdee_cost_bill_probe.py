"""本地调试：探测金蝶「成本计算单」（``CB_CostCalBill``）的取数参数与字段（只读，不落库）。

用途：产品线分析报表的「实际成本」要按**订单**取 ERP 成本计算单，本脚本用于确认：

1. 必录参数（核算组织 / 会计政策 / 核算体系 / 显示方式）各自填什么值能返回数据；
2. ``FieldKeys`` 里哪些列有值（金蝶不校验字段名，写错只返回空列，只能靠"试 + 看有没有值"反查）；
3. 按**销售订单号**（``FStartOrderBillNo``）过滤是否生效。

用法：
    python scripts/kingdee_cost_bill_probe.py --year 2026 --period 9
    python scripts/kingdee_cost_bill_probe.py --year 2026 --period 9 --order SO2026090001
    python scripts/kingdee_cost_bill_probe.py --orgs 100,106 --periods 8,9
    python scripts/kingdee_cost_bill_probe.py --load --out exports/cost_bill_sample.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# 探测脚本不需要应用日志；提前压掉，避免 loguru 轮转报错刷屏
os.environ.setdefault("LOGGER_LEVEL", "WARNING")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.kingdee.client import KingdeeClient, KingdeeClientConfig  # noqa: E402
from app.modules.erp.kingdee.model import KingdeeConnectionModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

FORM_ID = "CB_CostCalBill"

# 成本计算单的显示列（来源：金蝶 WebAPI 文档《成本计算单查询接口》）
FIELD_KEYS = (
    "FYearPeriod,FOrderBillNo,FOrderBillSeq,FCOSTCENTERNUMBER,FCOSTCENTERNAME,"
    "FPRODUCTID_FNUMBER,FPRODUCTID_FNAME,FSPECIFICATION,FPRODUCTEDTYPE,FBILLTYPENAME,"
    "FPRODUCTNO,FBILLSeq,FBILLSTATUS,FBOMNUMBERFIELD_FNUMBER,FBATCHFIELD_FNAME,FMTONO,"
    "FBASICUNITFIELD_FNAME,FPlanQty,"
    "FCOSTITEMID_FNUMBER,FCOSTITEMID_FNAME,"
    "FMATERIALFIELD_FNUMBER,FMATERIALFIELD_FNAME,"
    "FEXPENSEITEMFIELD_FNUMBER,FEXPENSEITEMFIELD_FNAME,"
    "FBeginQty,FBeginAmount,FAdjCurrInputQty,FAdjCurrInputAmount,"
    "FCurrInputQty,FCurrInputAmount,FSumInputQty,FSumInputAmount,"
    "FEndQty,FEndAmount,FCompleteQty,FProductUseQty,FProductUseCost,FCompleteAmount,"
    "FSumQualifiedInQty,FSumQualifiedInAmount,FSumCompleteQty,FSumProductUseQty,"
    "FSumProductUseCost,FSumCompleteAmount"
)

# 本报表关心的核心列（探测报告按此分组）
CORE_FIELDS = (
    "FOrderBillNo",
    "FPRODUCTID_FNUMBER",
    "FBOMNUMBERFIELD_FNUMBER",
    "FCOSTITEMID_FNAME",
    "FProductUseCost",
    "FCompleteQty",
    "FCompleteAmount",
    "FCurrInputAmount",
)


def build_model(
    year: str,
    period: str,
    org_code: str,
    policy: str,
    system: str,
    show_way: str,
    order_no: str = "",
    currency: str = "1",
) -> dict:
    """按文档拼 Model；未确认的必录项留空以便逐个试。"""
    return {
        "FACCTGSYSTEMID": {"FNumber": system},
        "FACCTGORGID": {"FNumber": org_code},
        "FACCTPOLICYID": {"FNumber": policy},
        "FYear": year,
        "FEndYear": year,
        "FPeriod": period,
        "FEndPeriod": period,
        "FSTARTCOSTCID": {"FNumber": ""},
        "FCurrencyID": {"FNumber": currency},
        "FENDCOSTCID": {"FNumber": ""},
        "FSTARTBILLNO": "",
        "FSTARTDATE": "1900-01-01",
        "FENDDATE": "1900-01-01",
        "FBILLTYPE": "",
        "FSTARTMATERIALID": {"FNumber": ""},
        "FENDBILLNO": "",
        "FENDMATERIALID": {"FNumber": ""},
        "FENDPROORDERID": "",
        "FSTARTCOSTITEMID": {"FNUMBER": ""},
        "FSTARTPROORDERID": "",
        "FSTARTEXPENSEID": {"FNumber": ""},
        "FENDCOSTITEMID": {"FNUMBER": ""},
        "FENDEXPENSEID": {"FNumber": ""},
        "FISSHOWDETAIL": "true",
        "FISSHOWMATERIA": "true",
        "FSHOWWAY": show_way,
        "FShowIndirectExpenseDetial": "false",
        "FSumGist": "",
        "FStartOrderBillNo": order_no,
        "FEndOrderBillNo": order_no,
        "FNOINCOMPNOSHOW": "false",
        "FSumPeriod": "false",
    }


def params(model: dict, field_keys: str, limit: int, filter_string: list | None = None) -> dict:
    return {
        "FieldKeys": field_keys,
        "SchemeId": "",
        "StartRow": 0,
        "Limit": limit,
        "IsVerifyBaseDataField": "true",
        "FilterString": filter_string or [],
        "Model": model,
    }


def unwrap(result) -> dict:
    for _ in range(4):
        if isinstance(result, dict) and isinstance(result.get("Result"), dict):
            result = result["Result"]
            continue
        if isinstance(result, list) and result:
            result = result[0]
            continue
        break
    return result if isinstance(result, dict) else {}


def response_error(result: dict) -> str:
    status = (result or {}).get("ResponseStatus") or {}
    errors = status.get("Errors") or []
    if not errors:
        return ""
    first = errors[0] if isinstance(errors[0], dict) else {}
    msg = str(first.get("Message") or first.get("FieldName") or "")
    return msg.replace("\r", " ").replace("\n", " ")[:220]


def column_stats(rows: list, fields: list[str]) -> None:
    for index, field in enumerate(fields):
        non_null = 0
        samples: list[str] = []
        for row in rows:
            if not isinstance(row, list) or index >= len(row):
                continue
            value = row[index]
            if value is None or value == "":
                continue
            non_null += 1
            if len(samples) < 3:
                samples.append(str(value)[:40])
        flag = "命中" if non_null else "空列"
        print(f"  {flag} {field:<30} 非空 {non_null:<6} 样例 {samples}")


async def load_client() -> KingdeeClient:
    async with async_db_session() as db:
        obj = (await db.execute(select(KingdeeConnectionModel).where(KingdeeConnectionModel.status == 0))).scalars().first()
        if obj is None:
            raise SystemExit("未找到启用的金蝶连接，请先配置 erp_kingdee_connection")
        secret = CryptoUtil.decrypt(obj.app_secret) if obj.app_secret else ""
        config = KingdeeClientConfig(
            server_url=obj.server_url,
            acct_id=obj.acct_id,
            username=obj.username,
            app_id=obj.app_id,
            app_secret=secret,
            lcid=obj.lcid,
            org_num=obj.org_num,
            connect_timeout=obj.connect_timeout,
            request_timeout=obj.request_timeout,
            proxy=obj.proxy or "",
        )
        print(f"已载入金蝶连接：{obj.name} @ {obj.server_url}")
    return KingdeeClient(config)


async def main() -> int:
    parser = argparse.ArgumentParser(description="探测金蝶成本计算单 CB_CostCalBill")
    parser.add_argument("--year", default="2026")
    parser.add_argument("--period", default="9")
    parser.add_argument("--org", default="100", help="核算组织编码 FACCTGORGID.FNumber")
    parser.add_argument("--policy", default="", help="会计政策编码 FACCTPOLICYID.FNumber")
    parser.add_argument("--system", default="", help="核算体系编码 FACCTGSYSTEMID.FNumber")
    parser.add_argument("--show-way", default="", help="显示方式 FSHOWWAY")
    parser.add_argument("--order", default="", help="销售订单号（过滤条件）")
    parser.add_argument("--orgs", default="", help="扫描多个核算组织编码，逗号分隔（如 100,101,106）")
    parser.add_argument("--periods", default="", help="扫描多个期间，逗号分隔（如 7,8,9）")
    parser.add_argument("--detail", default="false", help="FISSHOWDETAIL / FISSHOWMATERIA 取值")
    parser.add_argument("--currency", default="1", help="币别编码 FCurrencyID.FNumber（1=人民币）")
    parser.add_argument("--load", action="store_true", help="取数并输出列统计（默认只做参数矩阵）")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--out", default="", help="把结果写成 UTF-8 JSON 文件")
    parser.add_argument("--params-file", default="", help="直接使用给定的请求参数 JSON 文件（原样透传，不走内置 Model 模板）")
    args = parser.parse_args()

    client = await load_client()
    field_keys = FIELD_KEYS

    if args.params_file:
        request = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
        if args.limit:
            request["Limit"] = args.limit
        field_keys = str(request.get("FieldKeys") or "")
        print(f"\n=== {FORM_ID} 取数（参数来自 {args.params_file}）===")
        print(f"    Model={json.dumps(request.get('Model'), ensure_ascii=False)}")
        result = unwrap(await client.get_sys_report_data(FORM_ID, request))
        rows = result.get("Rows") if isinstance(result.get("Rows"), list) else []
        print(f"IsSuccess={result.get('IsSuccess')} RowCount={result.get('RowCount')} 取到 {len(rows)} 行")
        error = response_error(result)
        if error:
            print(f"错误：{error}")
        if rows:
            fields = [item.strip() for item in field_keys.split(",") if item.strip()]
            column_stats(rows, fields)
            print("\n首行原样：")
            print("  " + json.dumps(rows[0], ensure_ascii=False)[:1200])
        if args.out:
            Path(args.out).write_text(
                json.dumps({"form_id": FORM_ID, "params": request, "result": result}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"已写出 {args.out}")
        return 0

    if args.orgs:
        orgs = [item.strip() for item in args.orgs.split(",") if item.strip()]
        periods = [item.strip() for item in (args.periods or args.period).split(",") if item.strip()]
        print(f"\n=== 组织 × 期间扫描（policy={args.policy!r} system={args.system!r}）===")
        for org in orgs:
            for period in periods:
                model = build_model(
                    args.year, period, org, args.policy, args.system, args.show_way, args.order, args.currency
                )
                model["FISSHOWDETAIL"] = args.detail
                model["FISSHOWMATERIA"] = args.detail
                try:
                    result = unwrap(
                        await client.get_sys_report_data(FORM_ID, params(model, "FOrderBillNo", 5))
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"  org={org:<5} {args.year}-{period:<3} -> EXC {e}")
                    continue
                flag = "" if result.get("IsSuccess") else "  << 有错误"
                print(
                    f"  org={org:<5} {args.year}-{period:<3} -> "
                    f"IsSuccess={result.get('IsSuccess')} RowCount={result.get('RowCount')}"
                    f" {response_error(result)}{flag}"
                )
        return 0

    if not args.load:
        # 参数矩阵：确认必录项取值
        matrix = []
        for policy in (args.policy, "", "001"):
            for system in (args.system, "", "001"):
                for show_way in (args.show_way, "", "1", "2"):
                    combo = (policy, system, show_way)
                    if combo in matrix:
                        continue
                    matrix.append(combo)
        print(f"\n=== 参数矩阵（组织 {args.org}，期间 {args.year}-{args.period}）===")
        for policy, system, show_way in matrix:
            model = build_model(
                args.year, args.period, args.org, policy, system, show_way, args.order, args.currency
            )
            try:
                result = unwrap(await client.get_sys_report_data(FORM_ID, params(model, "FOrderBillNo", 5)))
            except Exception as e:  # noqa: BLE001
                print(f"  policy={policy!r:<6} system={system!r:<6} showway={show_way!r:<4} -> EXC {e}")
                continue
            row_count = result.get("RowCount")
            error = response_error(result)
            print(
                f"  policy={policy!r:<6} system={system!r:<6} showway={show_way!r:<4} "
                f"-> IsSuccess={result.get('IsSuccess')} RowCount={row_count} {error}"
            )
        return 0

    model = build_model(
        args.year, args.period, args.org, args.policy, args.system, args.show_way, args.order, args.currency
    )
    request = params(model, field_keys, args.limit)
    print(f"\n=== {FORM_ID} 取数（组织 {args.org}，期间 {args.year}-{args.period}，订单 {args.order or '不限'}）===")
    result = unwrap(await client.get_sys_report_data(FORM_ID, request))
    rows = result.get("Rows") if isinstance(result.get("Rows"), list) else []
    print(f"IsSuccess={result.get('IsSuccess')} RowCount={result.get('RowCount')} 取到 {len(rows)} 行")
    error = response_error(result)
    if error:
        print(f"错误：{error}")
    if rows:
        fields = [item.strip() for item in field_keys.split(",") if item.strip()]
        column_stats(rows, fields)
        print("\n首行原样：")
        print("  " + json.dumps(rows[0], ensure_ascii=False)[:1000])
    if args.out:
        Path(args.out).write_text(
            json.dumps({"form_id": FORM_ID, "params": request, "result": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已写出 {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    finally:
        pass
