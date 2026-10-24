"""重跑零售产品线指标：同步 type=3 + 产品字典 → 订单全链路 → 产品线宽表。

适用场景：CRM 补全/修正 `orderAnalyze?type=3` 的 `product_model` / `product_series`
（含逗号分隔的多型号、多系列）后，按期间重拉并重建零售产品线数据。

用法（在 ``backend`` 目录下执行）：
    python scripts/rerun_product_line_retail.py --dry-run
    python scripts/rerun_product_line_retail.py
    python scripts/rerun_product_line_retail.py --periods 2026-08,2026-09,2026-10
    python scripts/rerun_product_line_retail.py --skip-dict-sync --retries 3

默认期间为 2026-08 / 2026-09 / 2026-10；每期都会新增 calc_version，不覆盖历史版本。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    MetaSyncRunModel,
    SourceObjectModel,
)
from app.modules.metadata.sync import execute_meta_sync_job  # noqa: E402
from app.modules.order.build import build_period as build_order_period  # noqa: E402
from app.modules.product.build import build_period as build_product_period  # noqa: E402
from app.modules.product.model import ProductLineAnalysisModel  # noqa: E402
from app.modules.product.schema_guard import ensure_tables  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

DEFAULT_PERIODS = "2026-08,2026-09,2026-10"
RETAIL_OBJECT = "/hs/order/orderAnalyze?type=3"
MODEL_OBJECT = "/hs/product/getProductModel"
CATEGORY_OBJECT = "/hs/product/getProductCategory"


def banner(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


async def resolve_job_id(object_code: str) -> int:
    """按来源对象编码取一个启用的同步任务。"""
    async with async_db_session() as db:
        job_id = (
            await db.execute(
                select(MetaSyncJobModel.id)
                .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
                .where(
                    SourceObjectModel.code == object_code,
                    MetaSyncJobModel.status == 0,
                )
                .order_by(MetaSyncJobModel.id.asc())
                .limit(1)
            )
        ).scalar()
    if job_id is None:
        raise SystemExit(f"找不到启用的同步任务：{object_code}")
    return int(job_id)


async def latest_run(job_id: int, period_value: str | None = None) -> dict[str, object] | None:
    """只取轻量列；不要 SELECT *，rows_json 很大会触发 MySQL 排序内存上限。"""
    async with async_db_session() as db:
        stmt = select(
            MetaSyncRunModel.id,
            MetaSyncRunModel.status,
            MetaSyncRunModel.row_count,
            MetaSyncRunModel.period_value,
        ).where(MetaSyncRunModel.job_id == job_id)
        if period_value is not None:
            stmt = stmt.where(MetaSyncRunModel.period_value == period_value)
        stmt = stmt.order_by(MetaSyncRunModel.id.desc()).limit(1)
        row = (await db.execute(stmt)).first()
    if row is None:
        return None
    return {"id": row[0], "status": row[1], "row_count": row[2], "period_value": row[3]}


async def sync_once(
    job_id: int,
    period_value: str | None,
    label: str,
    retries: int,
    dry_run: bool,
) -> dict[str, object] | None:
    """执行一次同步，并校验确实产生了新的成功批次。"""
    before = await latest_run(job_id, period_value)
    if dry_run:
        print(f"  [dry-run] 同步 {label}（job={job_id}, period={period_value or '当前月'}）")
        return None

    for attempt in range(1, retries + 2):
        await execute_meta_sync_job(job_id, period_value=period_value)
        after = await latest_run(job_id, period_value)
        changed = after is not None and (before is None or after["id"] != before["id"])
        if changed and after["status"] == "success" and int(after["row_count"] or 0) > 0:
            print(
                f"  {label}: 批次 {after['id']}，{after['row_count']} 行"
                f"{f'（第 {attempt} 次尝试）' if attempt > 1 else ''}"
            )
            return after
        reason = (
            "未产生新批次"
            if not changed
            else f"状态={after['status']} 行数={after['row_count']}"
        )
        print(f"  {label}: 第 {attempt} 次同步未成功（{reason}）")
        before = after
        if attempt <= retries:
            await asyncio.sleep(2)

    raise SystemExit(f"同步失败：{label}（job={job_id}, period={period_value or '当前月'}）")


async def retail_summary(period_value: str) -> dict[str, float]:
    """读取该期间最新产品线版本中的零售指标汇总。"""
    async with async_db_session() as db:
        version = (
            await db.execute(
                select(func.max(ProductLineAnalysisModel.calc_version)).where(
                    ProductLineAnalysisModel.period_value == period_value
                )
            )
        ).scalar()
        if version is None:
            return {"version": 0, "amount": 0.0, "qty": 0.0, "unclassified_amount": 0.0}
        rows = (
            await db.execute(
                select(
                    ProductLineAnalysisModel.product_line_code,
                    ProductLineAnalysisModel.is_aggregate,
                    ProductLineAnalysisModel.extra,
                ).where(
                    ProductLineAnalysisModel.period_value == period_value,
                    ProductLineAnalysisModel.calc_version == version,
                    ProductLineAnalysisModel.is_aggregate.in_((1, 2)),
                )
            )
        ).all()

    total = {"version": int(version), "amount": 0.0, "qty": 0.0, "unclassified_amount": 0.0}
    for line, aggregate, extra in rows:
        extra = extra or {}
        amount = float(extra.get("PRD-X10") or 0)
        qty = float(extra.get("PRD-X11") or 0)
        if aggregate == 2:
            total["amount"] = amount
            total["qty"] = qty
        elif line == "未分类":
            total["unclassified_amount"] = amount
    return total


async def main() -> None:
    parser = argparse.ArgumentParser(description="重跑零售产品线指标")
    parser.add_argument("--periods", default=DEFAULT_PERIODS, help="期间，逗号分隔")
    parser.add_argument("--skip-dict-sync", action="store_true", help="跳过型号/系列字典同步")
    parser.add_argument("--skip-order-sync", action="store_true", help="跳过 type=3 零售订单同步")
    parser.add_argument("--keep-versions", type=int, default=3, help="订单全链路保留版本数")
    parser.add_argument("--retries", type=int, default=2, help="同步失败重试次数")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = parser.parse_args()

    periods = [item.strip() for item in args.periods.split(",") if item.strip()]
    if not periods:
        parser.error("--periods 不能为空")

    banner("零售产品线重跑计划")
    print(f"期间：{', '.join(periods)}")
    retail_job = await resolve_job_id(RETAIL_OBJECT)
    model_job = await resolve_job_id(MODEL_OBJECT)
    category_job = await resolve_job_id(CATEGORY_OBJECT)
    print(f"同步任务：零售={retail_job}  型号字典={model_job}  系列字典={category_job}")
    if args.dry_run:
        print("模式：dry-run（不写数据库、不调用外部接口）")

    if not args.skip_dict_sync:
        banner("[1/3] 同步产品字典")
        await sync_once(model_job, None, "型号字典", args.retries, args.dry_run)
        await sync_once(category_job, None, "系列字典", args.retries, args.dry_run)

    if not args.dry_run:
        created = await ensure_tables(async_engine)
        if created:
            print(f"补建缺失表：{', '.join(created)}")

    banner("[2/3] 按期间同步零售订单并重建订单全链路")
    order_versions: dict[str, int] = {}
    for period in periods:
        print(f"\n[{period}]")
        if not args.skip_order_sync:
            await sync_once(retail_job, period, "零售订单 type=3", args.retries, args.dry_run)
        if args.dry_run:
            print(f"  [dry-run] 重建订单全链路 {period}")
            continue
        async with async_db_session() as db, db.begin():
            result = await build_order_period(db, period, prune_versions=args.keep_versions)
        order_versions[period] = int(result["calc_version"])
        print(
            f"  订单全链路 v{result['calc_version']}：{result['order_count']} 张订单，"
            f"关联生产订单 {result['mo_linked_count']} 张"
        )

    banner("[3/3] 重建产品线宽表")
    for period in periods:
        print(f"\n[{period}]")
        if args.dry_run:
            print(f"  [dry-run] 重建产品线宽表 {period}")
            continue
        async with async_db_session() as db, db.begin():
            result = await build_product_period(db, period)
        print(
            f"  产品线 v{result['calc_version']}：产品线 {result['line_count']} 个、"
            f"SKU {result['sku_count']} 个、明细 {result['detail_count']} 行，"
            f"命中型号字典 {result['matched_rows']} / 未命中 {result['unmatched_rows']}"
        )
        summary = await retail_summary(period)
        print(
            f"  零售指标：金额 {summary['amount']:,.2f}、数量 {summary['qty']:g}，"
            f"未分类金额 {summary['unclassified_amount']:,.2f}"
        )

    banner("完成")
    if order_versions:
        versions = "，".join(f"{period}=v{version}" for period, version in order_versions.items())
        print(f"订单全链路版本：{versions}")
    print("产品线宽表已按期间追加新版本，历史版本保留。")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
