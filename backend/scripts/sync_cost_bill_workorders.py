"""按工单分批抓取金蝶成本计算单，落「工单级成本拆分」表。

为什么分批：整月 + ``FSHOWWAY=1`` 直查会被 ERP 中止（约 10 分钟「正在中止线程」）；
按工单（``FSTARTPROORDERID``）单查 1~3 秒。

用法：
    python scripts/sync_cost_bill_workorders.py --period 2026-09 --mode light
    python scripts/sync_cost_bill_workorders.py --period 2026-09 --mode full --limit 50
    python scripts/sync_cost_bill_workorders.py --period 2026-09 --reset   # 先清空该期间再抓

口径（初版）：
- 材料成本 = 成本项目 ``直接材料`` 的 ``FCompleteAmount`` 合计
- 人工成本 = 费用项目以 ``直接人工`` 开头 + ``工资`` / ``直接人工-计件工资`` / ``直接人工-临时工工资``
- 其余成本 = 除 ``材料成本`` 外的其余费用项目合计（制造费用，变动/固定待归类）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("LOGGER_LEVEL", "WARNING")

from k3cloud_webapi_sdk.main import K3CloudApiSdk  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.kingdee.model import KingdeeConnectionModel  # noqa: E402
from app.modules.order.model import OrderFullChainModel  # noqa: E402
from app.modules.product.model import CostBillWorkOrderModel  # noqa: E402
from app.modules.product.schema_guard import ensure_cost_bill_table  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

FORM_ID = "CB_CostCalBill"
FIELDS_LIGHT = (
    "FYearPeriod,FOrderBillNo,FPRODUCTNO,FPRODUCTID_FNUMBER,FCOSTITEMID_FNAME,"
    "FCompleteQty,FCurrInputAmount,FCompleteAmount"
)
FIELDS_FULL = (
    "FYearPeriod,FOrderBillNo,FPRODUCTNO,FPRODUCTID_FNUMBER,"
    "FCOSTITEMID_FNAME,FEXPENSEITEMFIELD_FNAME,FMATERIALFIELD_FNAME,"
    "FCompleteQty,FCurrInputAmount,FCompleteAmount"
)
LABOR_PREFIX = "直接人工"
LABOR_EXTRA = {"工资", "直接人工-计件工资", "直接人工-临时工工资"}
MATERIAL_EXPENSE = "材料成本"


def num(value) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def build_model(period: str, work_order: str, showway: str, detail: bool) -> dict:
    year, month = period.split("-")
    return {
        "FACCTGSYSTEMID": {"FNumber": "KJHSTX01_SYS"},
        "FACCTGORGID": {"FNumber": "100"},
        "FACCTPOLICYID": {"FNumber": "KJZC01_SYS"},
        "FYear": year,
        "FEndYear": year,
        "FPeriod": str(int(month)),
        "FEndPeriod": str(int(month)),
        "FCurrencyID": {"FNumber": "PRE001"},
        "FISSHOWDETAIL": "true" if detail else "false",
        "FISSHOWMATERIA": "true" if detail else "false",
        "FSHOWWAY": showway,
        "FShowIndirectExpenseDetial": "false",
        "FNOINCOMPNOSHOW": "false",
        "FSumPeriod": "false",
        "FSTARTPROORDERID": work_order,
        "FENDPROORDERID": work_order,
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


async def work_orders_of(db, period: str) -> list[tuple[str, str]]:
    """该期间的工单列表（工单号 + 产品编码），来自订单全链路。"""
    version = (
        await db.execute(
            select(func.max(OrderFullChainModel.calc_version)).where(
                OrderFullChainModel.period_value == period
            )
        )
    ).scalar()
    if version is None:
        return []
    rows = (
        await db.execute(
            select(OrderFullChainModel.extra).where(
                OrderFullChainModel.period_value == period,
                OrderFullChainModel.calc_version == version,
            )
        )
    ).scalars().all()
    result: dict[str, str] = {}
    for extra in rows:
        if not isinstance(extra, dict):
            continue
        work_order = str(extra.get("push_no") or "").strip()
        if work_order:
            result.setdefault(work_order, "")
    return [(k, v) for k, v in result.items()]


async def main() -> None:
    parser = argparse.ArgumentParser(description="按工单抓取成本计算单")
    parser.add_argument("--period", default="2026-09")
    parser.add_argument("--mode", choices=["light", "full"], default="light")
    parser.add_argument("--showway", default="1")
    parser.add_argument("--limit", type=int, default=0, help="最多抓多少个工单（0=全部）")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--reset", action="store_true", help="先删除该期间已有结果")
    args = parser.parse_args()

    detail = args.mode == "full"
    field_keys = FIELDS_FULL if detail else FIELDS_LIGHT
    fields = field_keys.split(",")
    index = {name: i for i, name in enumerate(fields)}

    # 迁移没跑（多 head / 被 stamp 跳过）时，这里自动补表，避免 1146 直接中断
    created = await ensure_cost_bill_table(async_engine)
    if created:
        print(f"补建缺失表：{', '.join(created)}（建议随后跑一次 alembic upgrade head 对齐版本号）")

    async with async_db_session() as db:
        if args.reset:
            await db.execute(delete(CostBillWorkOrderModel).where(CostBillWorkOrderModel.period_value == args.period))
            await db.commit()
        existing_rows = (
            await db.execute(
                select(CostBillWorkOrderModel.work_order, CostBillWorkOrderModel.extra).where(
                    CostBillWorkOrderModel.period_value == args.period
                )
            )
        ).all()
        existing = {
            row[0]: ((row[1] or {}).get("mode") if isinstance(row[1], dict) else None)
            for row in existing_rows
        }
        orders = await work_orders_of(db, args.period)
        obj = (
            await db.execute(select(KingdeeConnectionModel).where(KingdeeConnectionModel.status == 0))
        ).scalars().first()
        if obj is None:
            raise SystemExit("未找到启用的金蝶连接")
        config = {
            "server_url": obj.server_url, "acct_id": obj.acct_id, "username": obj.username,
            "app_id": obj.app_id, "app_secret": CryptoUtil.decrypt(obj.app_secret),
            "lcid": obj.lcid, "org_num": obj.org_num,
        }

    # full 模式下，之前 light 抓的行（没有费用项目字段，制造费用必为 0）要重抓升级
    todo = [
        (wo, code)
        for wo, code in orders
        if wo not in existing or (detail and existing[wo] != "full")
    ]
    if args.limit:
        todo = todo[: args.limit]
    upgrade = sum(1 for wo, _ in todo if wo in existing)
    print(
        f"期间 {args.period}｜模式 {args.mode}｜工单总数 {len(orders)}｜已完成 {len(existing)}"
        f"｜本次待抓 {len(todo)}（其中 light 升级 {upgrade}）"
    )
    if not todo:
        return

    sdk = K3CloudApiSdk(server_url=config["server_url"], timeout=args.timeout)
    sdk.InitConfig(
        acct_id=config["acct_id"], user_name=config["username"], app_id=config["app_id"],
        app_secret=config["app_secret"], server_url=config["server_url"], lcid=config["lcid"],
        org_num=config["org_num"], connect_timeout=args.timeout, request_timeout=args.timeout,
    )

    ok = failed = 0
    started = time.monotonic()
    async with async_db_session() as db:
        for i, (work_order, product_code) in enumerate(todo, 1):
            model = build_model(args.period, work_order, args.showway, detail)
            params = {
                "FieldKeys": field_keys, "SchemeId": "", "StartRow": 0, "Limit": 5000,
                "IsVerifyBaseDataField": "true", "FilterString": [], "Model": model,
            }
            try:
                raw = sdk.GetSysReportData(FORM_ID, json.dumps(params, ensure_ascii=False))
                result = unwrap(json.loads(raw) if isinstance(raw, str) else raw)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  [{i}/{len(todo)}] {work_order} 失败: {str(exc)[:80]}")
                continue

            rows = result.get("Rows") if isinstance(result.get("Rows"), list) else []
            material = labor = other = 0.0
            complete_qty = 0.0
            for row in rows:
                if not isinstance(row, list):
                    continue
                def cell(name: str):
                    j = index.get(name)
                    return row[j] if j is not None and j < len(row) else None
                # 完工数量只在「单据级汇总行」（成本项目/费用项目/子项物料三者都为空）上取，
                # 同工单多张单据要累加；明细行也会带数量，直接全加会把分母放大十几倍
                if not str(cell("FCOSTITEMID_FNAME") or "").strip() \
                        and not str(cell("FEXPENSEITEMFIELD_FNAME") or "").strip() \
                        and not str(cell("FMATERIALFIELD_FNAME") or "").strip():
                    complete_qty += num(cell("FCompleteQty"))
                amount = num(cell("FCompleteAmount"))
                cost_item = str(cell("FCOSTITEMID_FNAME") or "").strip()
                expense = str(cell("FEXPENSEITEMFIELD_FNAME") or "").strip()
                if cost_item == "直接材料":
                    material += amount
                elif expense and expense != MATERIAL_EXPENSE:
                    if expense.startswith(LABOR_PREFIX) or expense in LABOR_EXTRA:
                        labor += amount
                    else:
                        other += amount

            if work_order in existing:
                # 重抓升级：先删旧行，避免唯一键 (period_value, work_order) 冲突
                await db.execute(
                    delete(CostBillWorkOrderModel).where(
                        CostBillWorkOrderModel.period_value == args.period,
                        CostBillWorkOrderModel.work_order == work_order,
                    )
                )
            db.add(
                CostBillWorkOrderModel(
                    period_value=args.period,
                    work_order=work_order,
                    product_code=product_code or None,
                    complete_qty=round(complete_qty, 4),
                    material_cost=round(material, 4),
                    labor_cost=round(labor, 4),
                    other_cost=round(other, 4),
                    total_cost=round(material + labor + other, 4),
                    extra={"rows": len(rows), "mode": args.mode},
                )
            )
            ok += 1
            if i % 50 == 0:
                await db.commit()
                elapsed = time.monotonic() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(todo) - i) / rate / 60 if rate else 0
                print(f"  进度 {i}/{len(todo)}｜成功 {ok}｜失败 {failed}｜{rate:.2f} 工单/秒｜预计剩余 {eta:.1f} 分钟")
        await db.commit()

    elapsed = time.monotonic() - started
    print(f"完成：成功 {ok}｜失败 {failed}｜耗时 {elapsed/60:.1f} 分钟")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
