"""拉取金蝶成本计算单（``CB_CostCalBill``）明细，用于核对「显示方式」与成本项目拆分。

**按会计期间取数**（``FYear`` / ``FPeriod``），不走日期窗口；报表本身很重，
单月一次可能要几十秒到几十分钟，所以超时默认放宽到 1 小时。

用法：
    python scripts/fetch_cost_bill_detail.py --showway 1 --year 2026 --period 9
    python scripts/fetch_cost_bill_detail.py --showway 1 --year 2026 --period 9 --limit 500 --out ../exports/cost_bill_showway1.json
    python scripts/fetch_cost_bill_detail.py --showway 2 --year 2026 --period 9 --timeout 900
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import os  # noqa: E402

os.environ.setdefault("LOGGER_LEVEL", "WARNING")

from k3cloud_webapi_sdk.main import K3CloudApiSdk  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session  # noqa: E402
from app.modules.erp.kingdee.model import KingdeeConnectionModel  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

FORM_ID = "CB_CostCalBill"
DEFAULT_FIELDS = (
    "FYearPeriod,FOrderBillNo,FCOSTCENTERNAME,FPRODUCTID_FNUMBER,FPRODUCTID_FNAME,"
    "FPRODUCTNO,FBILLSeq,FBILLSTATUS,FBOMNUMBERFIELD_FNUMBER,FPlanQty,"
    "FCOSTITEMID_FNUMBER,FCOSTITEMID_FNAME,"
    "FEXPENSEITEMFIELD_FNUMBER,FEXPENSEITEMFIELD_FNAME,"
    "FMATERIALFIELD_FNUMBER,FMATERIALFIELD_FNAME,"
    "FBeginQty,FBeginAmount,FCurrInputQty,FCurrInputAmount,FSumInputQty,FSumInputAmount,"
    "FEndQty,FEndAmount,FCompleteQty,FProductUseQty,FProductUseCost,FCompleteAmount,"
    "FSumCompleteQty,FSumProductUseQty,FSumProductUseCost,FSumCompleteAmount"
)


def build_model(args: argparse.Namespace) -> dict:
    model = {
        "FACCTGSYSTEMID": {"FNumber": args.system},
        "FACCTGORGID": {"FNumber": args.org},
        "FACCTPOLICYID": {"FNumber": args.policy},
        "FYear": str(args.year),
        "FEndYear": str(args.year),
        "FPeriod": str(args.period),
        "FEndPeriod": str(args.period),
        "FCurrencyID": {"FNumber": args.currency},
        "FISSHOWDETAIL": "true" if args.detail else "false",
        "FISSHOWMATERIA": "true" if args.material else "false",
        "FSHOWWAY": str(args.showway),
        "FShowIndirectExpenseDetial": "false",
        "FNOINCOMPNOSHOW": "false",
        "FSumPeriod": "false",
    }
    if args.proorder:
        model["FSTARTPROORDERID"] = args.proorder
        model["FENDPROORDERID"] = args.proorder
    if args.material_no:
        model["FSTARTMATERIALID"] = {"FNumber": args.material_no}
        model["FENDMATERIALID"] = {"FNumber": args.material_no}
    if args.cost_center:
        model["FSTARTCOSTCID"] = {"FNumber": args.cost_center}
        model["FENDCOSTCID"] = {"FNumber": args.cost_center}
    return model


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


async def main() -> None:
    parser = argparse.ArgumentParser(description="按会计期间拉取成本计算单明细")
    parser.add_argument("--year", default="2026")
    parser.add_argument("--period", default="9")
    parser.add_argument("--org", default="100")
    parser.add_argument("--policy", default="KJZC01_SYS")
    parser.add_argument("--system", default="KJHSTX01_SYS")
    parser.add_argument("--currency", default="PRE001")
    parser.add_argument("--showway", default="1", help="显示方式：1/2/3/4")
    parser.add_argument("--detail", action="store_true", help="FISSHOWDETAIL=true")
    parser.add_argument("--material", action="store_true", help="FISSHOWMATERIA=true")
    parser.add_argument("--fields", default=DEFAULT_FIELDS)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--timeout", type=int, default=3600, help="读超时秒数（默认 3600）")
    parser.add_argument("--proorder", default="", help="工单编号（缩小范围，避免整月超时）")
    parser.add_argument("--material-no", default="", help="产品编码（缩小范围）")
    parser.add_argument("--cost-center", default="", help="成本中心编码（缩小范围）")
    parser.add_argument("--out", default="", help="把原始返回写成 JSON")
    args = parser.parse_args()

    async with async_db_session() as db:
        obj = (
            await db.execute(select(KingdeeConnectionModel).where(KingdeeConnectionModel.status == 0))
        ).scalars().first()
        if obj is None:
            raise SystemExit("未找到启用的金蝶连接")
        cfg = {
            "server_url": obj.server_url,
            "acct_id": obj.acct_id,
            "username": obj.username,
            "app_id": obj.app_id,
            "app_secret": CryptoUtil.decrypt(obj.app_secret),
            "lcid": obj.lcid,
            "org_num": obj.org_num,
        }

    sdk = K3CloudApiSdk(server_url=cfg["server_url"], timeout=args.timeout)
    sdk.InitConfig(
        acct_id=cfg["acct_id"], user_name=cfg["username"], app_id=cfg["app_id"],
        app_secret=cfg["app_secret"], server_url=cfg["server_url"], lcid=cfg["lcid"],
        org_num=cfg["org_num"], connect_timeout=args.timeout, request_timeout=args.timeout,
    )

    model = build_model(args)
    params = {
        "FieldKeys": args.fields,
        "SchemeId": "",
        "StartRow": 0,
        "Limit": args.limit,
        "IsVerifyBaseDataField": "true",
        "FilterString": [],
        "Model": model,
    }
    print(f"FormId={FORM_ID} 期间={args.year}-{args.period} 组织={args.org} 显示方式={args.showway} "
          f"detail={args.detail} material={args.material} Limit={args.limit} 超时={args.timeout}s")
    print(f"Model={json.dumps(model, ensure_ascii=False)}")
    print("请求中（按月期间取数，可能要几分钟到几十分钟）...", flush=True)

    started = time.monotonic()
    try:
        raw = sdk.GetSysReportData(FORM_ID, json.dumps(params, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - started
        print(f"失败（{elapsed:.1f}s）：{type(exc).__name__}: {str(exc)[:300]}")
        raise SystemExit(1)
    elapsed = time.monotonic() - started

    result = unwrap(json.loads(raw) if isinstance(raw, str) else raw)
    rows = result.get("Rows") if isinstance(result.get("Rows"), list) else []
    status = result.get("ResponseStatus") or {}
    print(f"耗时 {elapsed:.1f}s｜IsSuccess={result.get('IsSuccess')} RowCount={result.get('RowCount')} 取到 {len(rows)} 行")
    if status.get("Errors"):
        print("错误：", str(status["Errors"])[:400])

    fields = [item.strip() for item in args.fields.split(",") if item.strip()]
    if rows:
        print("列覆盖：")
        for index, name in enumerate(fields):
            non_null = 0
            samples: list[str] = []
            for row in rows:
                if not isinstance(row, list) or index >= len(row):
                    continue
                if row[index] in (None, ""):
                    continue
                non_null += 1
                if len(samples) < 2:
                    samples.append(str(row[index])[:30])
            print(f"  {'命中' if non_null else '空列'} {name:<30} {non_null:<6} {samples}")
        print("首行：", json.dumps(rows[0], ensure_ascii=False)[:600])

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps({"form_id": FORM_ID, "params": params, "elapsed": round(elapsed, 1), "result": result},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已写出：{args.out}")


if __name__ == "__main__":
    asyncio.run(main())
