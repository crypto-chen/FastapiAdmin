"""回填订单全链路宽表的 MES 新增字段（历史数据一次性补齐）。

为 ``/open/v1/mes/orders`` 增加以下字段后，新构建的期间由 ``order/build.py`` 自动写入：

- ``extra.principal_id`` / ``extra.principal_name``：负责人（CRM ``principal_id`` → 业务员姓名）
- ``extra.price``：单价（CRM ``price``）
- ``extra.important``：是否重要（1=重要，2=常规）
- ``extra.is_full_inspection``：是否全检（1=是，2=否）

历史期间用本脚本从已同步的 CRM 订单批次回填，不必全量重建订单宽表。

用法：
    python scripts/backfill_order_mes_fields.py                 # 预演，只统计不写库
    python scripts/backfill_order_mes_fields.py --apply         # 写入历史最新版本
    python scripts/backfill_order_mes_fields.py --apply --period 2026-10
"""

from __future__ import annotations

import argparse
import asyncio
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
from app.modules.metadata.sync import extract_payload_rows  # noqa: E402
from app.modules.order.build import SCHEMA_VERSION  # noqa: E402
from app.modules.order.model import OrderFullChainModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

ORDER_OBJECTS = ("/hs/order/orderAnalyze?type=1", "/hs/order/orderAnalyze?type=2")
NEW_KEYS = ("principal_id", "price", "important", "is_full_inspection")
CRM_SOURCE_TYPE = "crm"


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == "-"


def _to_number(value: Any) -> float | None:
    if _is_empty(value):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_number(value)
    return int(number) if number is not None else None


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
        name = str(source_name or "").strip()
        if crm_id is not None and name:
            names[str(crm_id)] = name
    return names


async def _period_runs(db, periods: set[str] | None) -> dict[str, list[tuple[str, int]]]:
    """每个期间的全部成功批次（按 id 升序），与构建时 ``merged_order_rows`` 的口径一致。

    只取最新一条会漏掉「最新批次里已被删除、但历史批次仍有」的订单；按升序合并、新批次覆盖非空字段，
    才能覆盖宽表里的全部订单。
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
            .order_by(MetaSyncRunModel.id.asc())
        )
    ).all()
    picked: dict[str, list[tuple[str, int]]] = {}
    for run_id, period, code in rows:
        period = str(period or "")
        if not period or (periods and period not in periods):
            continue
        picked.setdefault(period, []).append((str(code), int(run_id)))
    return picked


async def _fields_by_order(db, run_id: int) -> dict[str, dict[str, Any]]:
    run = await db.get(MetaSyncRunModel, run_id)
    if run is None:
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for row in extract_payload_rows(run.rows_json or {}):
        if str(row.get("status") or "").strip() == "522":
            continue
        number = str(row.get("number") or "").strip()
        if not number:
            continue
        if all(_is_empty(row.get(key)) for key in NEW_KEYS):
            # 2026-10-13 改版后的 6 字段批次没有这些字段，跳过，等更早的完整批次
            continue
        principal_raw = row.get("principal_id")
        price = _to_number(row.get("price"))
        mapping[number] = {
            "principal_id": _to_int(principal_raw),
            "principal_raw": str(principal_raw) if not _is_empty(principal_raw) else None,
            "price": round(price, 4) if price is not None else None,
            "important": _to_int(row.get("important")),
            "is_full_inspection": _to_int(row.get("is_full_inspection")),
        }
    return mapping


def _chunks(items: list[str], size: int = 500) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


async def _backfill_period(
    db,
    period: str,
    order_fields: dict[str, dict[str, Any]],
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
    for chunk in _chunks(list(order_fields)):
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
            fields = order_fields.get(row.order_number)
            if not fields:
                continue
            principal_raw = fields.get("principal_raw")
            principal_name = person_names.get(principal_raw) if principal_raw else None
            if principal_raw and not principal_name:
                missing_name += 1
            extra = dict(row.extra or {})
            extra["principal_id"] = fields["principal_id"]
            extra["principal_name"] = principal_name
            extra["price"] = fields["price"]
            extra["important"] = fields["important"]
            extra["is_full_inspection"] = fields["is_full_inspection"]
            extra["schema_version"] = SCHEMA_VERSION
            if apply:
                row.extra = extra
            updated += 1
        if apply:
            await db.flush()

    return {
        "period": period,
        "version": int(version),
        "orders": len(order_fields),
        "updated": updated,
        "missing_name": missing_name,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="回填 MES 订单负责人/单价/重要/全检字段")
    parser.add_argument("--apply", action="store_true", help="实际写库；缺省只预演统计")
    parser.add_argument("--period", default=None, help="只处理指定期间，多个用逗号分隔")
    args = parser.parse_args()

    periods = {item.strip() for item in args.period.split(",") if item.strip()} if args.period else None
    async with async_db_session() as db:
        person_names = await _person_names(db)
        runs = await _period_runs(db, periods)
        run_count = sum(len(items) for items in runs.values())
        print(f"待处理 CRM 订单批次 {run_count} 个，CRM 人员姓名 {len(person_names)} 个")

        by_period: dict[str, dict[str, dict[str, Any]]] = {}
        for period in sorted(runs):
            # 每个来源对象先按批次升序合并，新批次覆盖非空字段（同构建逻辑）
            by_code: dict[str, dict[str, dict[str, Any]]] = {}
            for code, run_id in runs[period]:
                mapping = await _fields_by_order(db, run_id)
                if not mapping:
                    continue
                merged = by_code.setdefault(code, {})
                for number, fields in mapping.items():
                    target = merged.setdefault(
                        number,
                        {
                            "principal_id": None,
                            "principal_raw": None,
                            "price": None,
                            "important": None,
                            "is_full_inspection": None,
                        },
                    )
                    for key, value in fields.items():
                        if value is not None:
                            target[key] = value
            # 与构建顺序一致：内贸优先，同一订单号已存在时不覆盖
            period_fields: dict[str, dict[str, Any]] = {}
            for code in ORDER_OBJECTS:
                for number, fields in by_code.get(code, {}).items():
                    period_fields.setdefault(number, fields)
            if period_fields:
                by_period[period] = period_fields

        totals = {"updated": 0, "missing_name": 0}
        for period in sorted(by_period):
            order_fields = by_period[period]
            result = await _backfill_period(db, period, order_fields, person_names, args.apply)
            totals["updated"] += result["updated"]
            totals["missing_name"] += result["missing_name"]
            print(
                f"期间 {period} v{result['version']}：订单 {result['orders']}，"
                f"{'已写入' if args.apply else '待写入'} {result['updated']}，负责人姓名缺失 {result['missing_name']}"
            )
            if args.apply:
                await db.commit()

        print(f"完成：{'写入' if args.apply else '预演'} {totals['updated']} 行，负责人姓名缺失 {totals['missing_name']} 行")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
