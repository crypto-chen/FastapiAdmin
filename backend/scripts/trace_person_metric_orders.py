"""追溯业务员指标由哪些订单计算而来（只读）。

以「接单未税」STF-13 为例：

    python scripts/trace_person_metric_orders.py --period 2026-10 --person lixinhui
    python scripts/trace_person_metric_orders.py --period 2026-10 --person 林银华
    python scripts/trace_person_metric_orders.py --code STF-41 --period 2026-10 --person lixinhui

脚本按指标定义复刻取数逻辑：
- 来源对象（内贸/外贸/零售）与同步任务；
- 有效状态 / 行过滤（新老客户、订单类型等）；
- 归期字段（STF-13 是收款日期 collectiontime，其余多数是建单月 createtime）；
- 回看期数（STF-13 回看 12 期，订单可能是以前月份建的）。

输出每张参与计算的订单及金额，并和 metric_value 里该业务员的指标值对账。
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel  # noqa: E402
from app.modules.metric.engine import (  # noqa: E402
    _amount_terms,
    _cell,
    _datetime_in_period,
    _field_order,
    _load_person_index,
    _load_run_payload,
    _parse_amount,
    _parse_datetime_value,
    _payload_rows,
    _row_matches_filters,
    _row_status_allowed,
    _text,
    shift_period,
)
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def resolve_person(db, target: str) -> tuple[str, str]:
    """返回 (CRM create_id, 展示名)。支持 create_id / 人员编码 / 姓名。"""
    index = await _load_person_index(db)
    if target in index:
        meta = index[target]
        return target, meta.get("person_name") or meta.get("person_code") or target
    for raw_id, meta in index.items():
        if target in {meta.get("person_code"), meta.get("person_name")}:
            return raw_id, meta.get("person_name") or target
    return target, target


async def main() -> None:
    parser = argparse.ArgumentParser(description="追溯业务员指标参与计算的订单")
    parser.add_argument("--code", default="STF-13", help="指标编码或 Excel 编码，默认 STF-13")
    parser.add_argument("--period", required=True, help="期间 YYYY-MM")
    parser.add_argument("--person", required=True, help="业务员：编码 / 姓名 / CRM create_id")
    parser.add_argument("--limit", type=int, default=200, help="最多打印多少行，默认 200")
    args = parser.parse_args()

    async with async_db_session() as db:
        metric = (
            await db.execute(
                select(MetricDefModel).where(
                    (MetricDefModel.code == args.code) | (MetricDefModel.excel_code == args.code)
                )
            )
        ).scalars().first()
        if metric is None:
            raise SystemExit(f"指标不存在：{args.code}")

        config = dict(metric.measures or {})
        if config.get("kind") != "crm_person_amount":
            raise SystemExit(f"{args.code} 不是按订单明细取数的业务员指标（kind={config.get('kind')}）")

        period_type = str(metric.period_type or "month")
        period = args.period
        lookback = max(int(config.get("lookback_periods") or 1), 1)
        forward = max(int(config.get("forward_periods") or 0), 0)
        period_field = str(config.get("period_field") or "")
        person_field = str(config.get("person_field") or "create_id")

        raw_person, person_name = await resolve_person(db, args.person)
        print(
            f"指标 {metric.excel_code or metric.code} {metric.name}｜期间 {period}｜"
            f"业务员 {person_name}（{raw_person}）｜归期字段 {period_field or '建单月 createtime'}"
        )

        total = 0.0
        shown = 0
        matched = 0
        for comp in config.get("components") or []:
            if not isinstance(comp, dict):
                continue
            cfg = {**config, **comp}
            object_code = str(comp.get("source_object_code") or "").strip()
            if not object_code:
                continue
            object_id = (
                await db.execute(
                    select(SourceObjectModel.id).where(SourceObjectModel.code == object_code)
                )
            ).scalars().first()
            if object_id is None:
                print(f"[跳过] 来源对象不存在：{object_code}")
                continue
            jobs = (
                await db.execute(
                    select(
                        MetaSyncJobModel.id,
                        MetaSyncJobModel.request_params,
                    ).where(
                        MetaSyncJobModel.source_object_id == object_id,
                        MetaSyncJobModel.status == 0,
                    )
                )
            ).all()
            terms = _amount_terms(cfg)
            comp_total = 0.0
            comp_rows = 0
            for offset in range(-forward, lookback):
                load_period = shift_period(period_type, period, -offset) if offset else period
                for job_id, params in jobs:
                    payload = await _load_run_payload(int(job_id), load_period, merge_runs=True)
                    rows = _payload_rows(payload) or []
                    if not rows:
                        continue
                    fields = _field_order(dict(params or {}))
                    for row in rows:
                        if not _row_status_allowed(row, fields, cfg):
                            continue
                        if not _row_matches_filters(row, fields, cfg.get("row_filters")):
                            continue
                        if period_field:
                            moment = _parse_datetime_value(_cell(row, fields, period_field))
                            if not _datetime_in_period(moment, period_type, period):
                                continue
                        person = _text(_cell(row, fields, person_field))
                        if person != raw_person:
                            continue
                        amount = sum(
                            sign * _parse_amount(_cell(row, fields, field))
                            for field, sign in terms
                        )
                        total += amount
                        comp_total += amount
                        comp_rows += 1
                        matched += 1
                        if shown < args.limit:
                            number = _text(_cell(row, fields, "number"))
                            date_value = _text(_cell(row, fields, period_field)) if period_field else ""
                            customer_code = _text(_cell(row, fields, "customer_code")) or _text(
                                _cell(row, fields, "customer_number")
                            )
                            customer_name = _text(_cell(row, fields, "customer_name")) or _text(
                                _cell(row, fields, "customer_name_retail")
                            )
                            print(
                                f"  {comp.get('label') or object_code}｜{number}｜{date_value}｜"
                                f"{customer_code or '-'} {customer_name or ''}｜{round(amount, 2)}"
                            )
                            shown += 1
            print(
                f"  [{comp.get('label') or object_code}] 订单 {comp_rows} 张，"
                f"金额 {round(comp_total, 2)}"
            )

        print(f"合计：订单 {matched} 张，金额 {round(total, 2)}")
        if shown < matched:
            print(f"（仅打印前 {shown} 行，可用 --limit 调整）")

        value = (
            await db.execute(
                select(MetricValueModel.value)
                .where(
                    MetricValueModel.metric_id == metric.id,
                    MetricValueModel.period_value == period,
                    MetricValueModel.person_code == args.person,
                    MetricValueModel.person_code.is_not(None),
                )
                .order_by(MetricValueModel.calc_time.desc())
                .limit(1)
            )
        ).scalars().first()
        if value is None:
            value = (
                await db.execute(
                    select(MetricValueModel.value)
                    .where(
                        MetricValueModel.metric_id == metric.id,
                        MetricValueModel.period_value == period,
                        MetricValueModel.person_name == person_name,
                        MetricValueModel.person_code.is_not(None),
                    )
                    .order_by(MetricValueModel.calc_time.desc())
                    .limit(1)
                )
            ).scalars().first()
        print(f"metric_value 指标值：{value}（差 {round(float(value or 0) - total, 2)}）")


if __name__ == "__main__":
    asyncio.run(main())
