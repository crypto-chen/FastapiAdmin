"""回填订单全链路宽表的「负责工程」字段（历史数据一次性补齐）。

CRM ``orderAnalyze`` 的 ``principal_engineering`` 是负责工程的 CRM 用户ID。
订单宽表新增 ``extra.engineer_code`` / ``extra.engineer_name`` 后：

- 新构建的期间由 ``order/build.py`` 自动写入；
- 历史期间用本脚本从已同步的 CRM 订单批次回填，不必全量重建订单。

用法：
    python scripts/backfill_order_engineer.py                 # 预演，只统计不写库
    python scripts/backfill_order_engineer.py --apply         # 写入历史最新版本
    python scripts/backfill_order_engineer.py --apply --period 2026-09
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.masterdata.model import SourcePersonModel  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel  # noqa: E402
from app.modules.order.model import OrderFullChainModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

ORDER_OBJECTS = ("/hs/order/orderAnalyze?type=1", "/hs/order/orderAnalyze?type=2")
MES_SCHEMA_VERSION = "2026-11-03"
CRM_SOURCE_TYPE = "crm"


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [item for item in data["data"] if isinstance(item, dict)]
    return []


async def _person_names(db) -> dict[str, str]:
    """CRM 用户ID → 姓名（source_person.raw_json.id）。"""
    rows = (
        await db.execute(
            select(SourcePersonModel.source_name, SourcePersonModel.raw_json).where(
                SourcePersonModel.source_type == CRM_SOURCE_TYPE,
                SourcePersonModel.is_deleted == False,  # noqa: E712
            )
        )
    ).all()
    names: dict[str, str] = {}
    for source_name, raw in rows:
        raw = raw if isinstance(raw, dict) else {}
        crm_id = raw.get("id")
        if crm_id is None:
            continue
        name = str(source_name or "").strip()
        if name:
            names[str(crm_id)] = name
    return names


async def _order_runs(db, periods: set[str] | None) -> list[dict]:
    """全部成功批次（按 id 倒序），由调用方按期间挑「带负责工程字段」的最新批次。

    CRM 2026-10-13 改版后的批次只有 6 个字段，会覆盖同期间的完整批次；
    不能只看最新一条，否则历史期间永远回填不到负责工程。
    """
    rows = (
        await db.execute(
            select(
                MetaSyncRunModel.id,
                MetaSyncRunModel.period_value,
                SourceObjectModel.code,
            )
            .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
            .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
            .where(
                SourceObjectModel.code.in_(ORDER_OBJECTS),
                MetaSyncRunModel.status == "success",
                MetaSyncRunModel.period_value.is_not(None),
            )
            .order_by(MetaSyncRunModel.id.desc())
        )
    ).all()
    picked: list[dict] = []
    for run_id, period, code in rows:
        period = str(period or "")
        if not period or (periods and period not in periods):
            continue
        picked.append({"run_id": int(run_id), "period": period, "code": str(code)})
    return picked


async def _engineer_by_order(db, run_id: int) -> dict[str, str]:
    run = await db.get(MetaSyncRunModel, run_id)
    if run is None:
        return {}
    mapping: dict[str, str] = {}
    for row in _rows(run.rows_json):
        if str(row.get("status") or "").strip() == "522":
            continue
        number = str(row.get("number") or "").strip()
        engineer = row.get("principal_engineering")
        if number and engineer not in (None, ""):
            mapping[number] = str(engineer)
    return mapping


def _chunks(items: list[str], size: int = 500) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


async def _backfill_period(
    db,
    period: str,
    order_engineer: dict[str, str],
    person_names: dict[str, str],
    apply: bool,
) -> dict:
    version = (
        await db.execute(
            select(func.max(OrderFullChainModel.calc_version)).where(
                OrderFullChainModel.period_value == period,
                OrderFullChainModel.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar()
    if not version:
        return {"period": period, "version": None, "orders": 0, "updated": 0, "missing_name": 0}

    updated = 0
    missing_name = 0
    numbers = list(order_engineer)
    for chunk in _chunks(numbers):
        rows = (
            (
                await db.execute(
                    select(OrderFullChainModel).where(
                        OrderFullChainModel.period_value == period,
                        OrderFullChainModel.calc_version == int(version),
                        OrderFullChainModel.trade_type.in_(("domestic", "export")),
                        OrderFullChainModel.order_number.in_(chunk),
                        OrderFullChainModel.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            engineer_code = order_engineer.get(row.order_number)
            if not engineer_code:
                continue
            engineer_name = person_names.get(engineer_code)
            if not engineer_name:
                missing_name += 1
            extra = dict(row.extra or {})
            extra["engineer_code"] = engineer_code
            extra["engineer_name"] = engineer_name
            extra["schema_version"] = MES_SCHEMA_VERSION
            if apply:
                row.extra = extra
            updated += 1
        if apply:
            await db.flush()

    return {
        "period": period,
        "version": int(version),
        "orders": len(numbers),
        "updated": updated,
        "missing_name": missing_name,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="回填订单负责工程字段")
    parser.add_argument("--apply", action="store_true", help="实际写库；缺省只预演统计")
    parser.add_argument("--period", default=None, help="只处理指定期间，多个用逗号分隔")
    args = parser.parse_args()

    periods = {item.strip() for item in args.period.split(",") if item.strip()} if args.period else None
    async with async_db_session() as db:
        person_names = await _person_names(db)
        runs = await _order_runs(db, periods)
        print(f"待处理 CRM 订单批次 {len(runs)} 个，CRM 人员姓名 {len(person_names)} 个")

        by_period: dict[str, dict[str, str]] = {}
        covered: set[tuple[str, str]] = set()
        for item in runs:
            key = (item["code"], item["period"])
            if key in covered:
                continue
            mapping = await _engineer_by_order(db, item["run_id"])
            if not mapping:
                continue
            covered.add(key)
            target = by_period.setdefault(item["period"], {})
            target.update(mapping)

        totals = {"updated": 0, "missing_name": 0}
        for period in sorted(by_period):
            order_engineer = by_period[period]
            result = await _backfill_period(db, period, order_engineer, person_names, args.apply)
            totals["updated"] += result["updated"]
            totals["missing_name"] += result["missing_name"]
            print(f"期间 {period} v{result['version']}：订单 {result['orders']}，{'已写入' if args.apply else '待写入'} {result['updated']}，工程姓名缺失 {result['missing_name']}")
            if args.apply:
                await db.commit()

        print(f"完成：{'写入' if args.apply else '预演'} {totals['updated']} 行，工程姓名缺失 {totals['missing_name']} 行")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
