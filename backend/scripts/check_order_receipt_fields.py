"""校验订单全链路里的回款/线索字段是否已落库。

用法：
    python scripts/check_order_receipt_fields.py
    python scripts/check_order_receipt_fields.py --period 2026-11 --limit 5
"""

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
from app.modules.order.model import OrderFullChainModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

FIELDS = ("claim_amount", "deposit_claim_amount", "first_receipt_date", "receipt_rate", "receipt_cycle", "clue_id")


async def latest_scope(db, period_value: str | None) -> tuple[str | None, int]:
    if not period_value:
        period_value = (
            await db.execute(select(func.max(OrderFullChainModel.period_value)))
        ).scalar()
    if not period_value:
        return None, 0
    version = (
        await db.execute(
            select(func.max(OrderFullChainModel.calc_version)).where(
                OrderFullChainModel.period_value == period_value
            )
        )
    ).scalar()
    return str(period_value), int(version or 0)


async def main() -> None:
    parser = argparse.ArgumentParser(description="校验订单全链路回款/线索字段")
    parser.add_argument("--period", default=None, help="期间 YYYY-MM，缺省取最新期间")
    parser.add_argument("--limit", type=int, default=5, help="打印样本行数")
    args = parser.parse_args()

    async with async_db_session() as db:
        period_value, calc_version = await latest_scope(db, args.period)
        if not period_value or not calc_version:
            print("没有可校验的订单全链路版本")
            return
        base = [
            OrderFullChainModel.period_value == period_value,
            OrderFullChainModel.calc_version == calc_version,
            OrderFullChainModel.is_deleted == False,  # noqa: E712
        ]
        total = (
            await db.execute(select(func.count()).select_from(OrderFullChainModel).where(*base))
        ).scalar() or 0
        rows = (
            await db.execute(
                select(
                    OrderFullChainModel.order_number,
                    OrderFullChainModel.intake_untaxed,
                    OrderFullChainModel.extra,
                )
                .where(*base)
                .order_by(OrderFullChainModel.order_number)
            )
        ).all()

        counters = dict.fromkeys(FIELDS, 0)
        claim_sum = 0.0
        deposit_claim_sum = 0.0
        for _number, _intake, extra in rows:
            extra = extra or {}
            for name in FIELDS:
                if extra.get(name) not in (None, ""):
                    counters[name] += 1
            if extra.get("claim_amount") not in (None, ""):
                claim_sum += float(extra["claim_amount"])
            if extra.get("deposit_claim_amount") not in (None, ""):
                deposit_claim_sum += float(extra["deposit_claim_amount"])

        print(f"期间 {period_value} 版本 v{calc_version}：订单 {total} 张")
        for name in FIELDS:
            print(f"  {name}: {counters[name]} 张有值")
        print(f"  回款金额合计: {round(claim_sum, 4)}")
        print(f"  回款定金合计: {round(deposit_claim_sum, 4)}")

        samples = [
            (number, intake, extra or {})
            for number, intake, extra in rows
            if (extra or {}).get("claim_amount") not in (None, "", 0, 0.0)
        ][: args.limit]
        print(f"样本（前 {len(samples)} 张有回款的订单）：")
        for number, intake, extra in samples:
            print(
                f"  {number}: 接单未税={intake}, 回款={extra.get('claim_amount')}, "
                f"回款定金={extra.get('deposit_claim_amount')}, 回款日期={extra.get('first_receipt_date')}, "
                f"回款率={extra.get('receipt_rate')}, 回款周期={extra.get('receipt_cycle')}, "
                f"线索ID={extra.get('clue_id')}"
            )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
