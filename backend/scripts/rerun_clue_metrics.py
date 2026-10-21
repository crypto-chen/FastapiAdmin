"""线索指标口径切换后重跑（STF-42/43/44）。

用途：线索接口新增 ``deal``（1=已转化订单 / 2=未转化）后，按最新口径
重拉近 30 天线索批次，并重算：

- STF-42 近30天线索数量：全部线索（只取最近一次成功批次）
- STF-43 近30天成交线索数量：``deal=1``
- STF-44 线索转化率：STF-43 ÷ STF-42 × 100%

用法（在 ``backend`` 目录执行）：

    python scripts/rerun_clue_metrics.py
    python scripts/rerun_clue_metrics.py --period 2026-10
    python scripts/rerun_clue_metrics.py --start 2026-08 --end 2026-10
    python scripts/rerun_clue_metrics.py --period 2026-10 --no-refresh

默认期间为当前月；``--start/--end`` 为闭区间（含首尾）。
不加 ``--no-refresh`` 时会先重拉线索批次（当前月按真实时间、历史月按该月 1 日），
再逐期重算三个指标，最后用批次明细核对合计。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel  # noqa: E402
from app.modules.metadata.sync import execute_meta_sync_job  # noqa: E402
from app.modules.metric.engine import _payload_rows, execute_metric_calc  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CLUE_PATH = "/hs/clue/getClueList"
CODES = [
    "marketing_person_clue_count_30d",  # STF-42
    "marketing_person_clue_deal_count_30d",  # STF-43
    "marketing_person_clue_conversion_rate",  # STF-44
]

# CLI 场景只保留控制台输出：默认日志文件被运行中的后端服务占用
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


async def _latest_value(metric_id: int, period: str) -> tuple[int | None, float | None, int]:
    """返回 (calc_version, 合计行值, 业务员行数)。"""
    async with async_db_session() as db:
        version = (
            await db.execute(
                select(MetricValueModel.calc_version)
                .where(
                    MetricValueModel.metric_id == metric_id,
                    MetricValueModel.period_value == period,
                )
                .order_by(MetricValueModel.calc_version.desc())
                .limit(1)
            )
        ).scalar()
        if version is None:
            return None, None, 0
        rows = (
            await db.execute(
                select(MetricValueModel.value, MetricValueModel.person_code).where(
                    MetricValueModel.metric_id == metric_id,
                    MetricValueModel.period_value == period,
                    MetricValueModel.calc_version == int(version),
                )
            )
        ).all()
    total = round(sum(float(value) for value, person in rows if person is None), 4)
    persons = sum(1 for _value, person in rows if person is not None)
    return int(version), total, persons


async def _latest_clue_rows(job_ids: list[int], period: str) -> list[dict]:
    async with async_db_session() as db:
        run = (
            await db.execute(
                select(MetaSyncRunModel)
                .where(
                    MetaSyncRunModel.job_id.in_(job_ids),
                    MetaSyncRunModel.period_value == period,
                    MetaSyncRunModel.status == "success",
                )
                .order_by(MetaSyncRunModel.id.desc())
                .limit(1)
            )
        ).scalars().first()
    if run is None:
        return []
    return [row for row in (_payload_rows(dict(run.rows_json or {})) or []) if isinstance(row, dict)]


def _count(rows: list[dict]) -> tuple[int, int]:
    """返回 (有负责人的线索数, 有负责人的 deal=1 线索数)。"""
    total = 0
    deal = 0
    for row in rows:
        person = str(row.get("principal_id") or "").strip()
        if not person:
            continue
        total += 1
        if str(row.get("deal") or "").strip() == "1":
            deal += 1
    return total, deal


def _months(start: str, end: str) -> list[str]:
    """``YYYY-MM`` 闭区间内的月份列表。"""
    begin = datetime.strptime(start, "%Y-%m")
    finish = datetime.strptime(end, "%Y-%m")
    if begin > finish:
        raise SystemExit(f"起始期间不能晚于结束期间: {start} > {end}")
    periods: list[str] = []
    cursor = begin
    while cursor <= finish:
        periods.append(cursor.strftime("%Y-%m"))
        cursor = (
            datetime(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1)
        )
    return periods


async def main() -> None:
    parser = argparse.ArgumentParser(description="线索指标口径切换后重跑 STF-42/43/44")
    parser.add_argument("--period", action="append", default=None, help="期间，可重复；缺省为当前月")
    parser.add_argument("--start", default=None, help="起始期间（含），如 2026-08")
    parser.add_argument("--end", default=None, help="结束期间（含），如 2026-10")
    parser.add_argument("--no-refresh", action="store_true", help="不重拉线索批次，直接用库里最近一次成功批次")
    args = parser.parse_args()

    if args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit("--start 与 --end 必须成对指定")
        periods = _months(args.start, args.end)
    elif args.period:
        periods = list(args.period)
    else:
        periods = [datetime.now().strftime("%Y-%m")]
    # 去重并保持顺序
    periods = list(dict.fromkeys(periods))

    async with async_db_session() as db:
        metrics = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code.in_(CODES)))
        ).scalars().all()
        by_code = {str(metric.code): metric for metric in metrics}
        missing = [code for code in CODES if code not in by_code]
        if missing:
            raise SystemExit(f"指标不存在，请先执行 seed_crm_person_metrics.py: {missing}")

        source = (
            await db.execute(select(SourceObjectModel).where(SourceObjectModel.code == CLUE_PATH))
        ).scalars().first()
        if source is None:
            raise SystemExit(f"来源对象不存在，请先执行 seed_crm_person_metrics.py: {CLUE_PATH}")
        jobs = (
            await db.execute(
                select(MetaSyncJobModel).where(
                    MetaSyncJobModel.source_object_id == source.id,
                    MetaSyncJobModel.status == 0,
                )
            )
        ).scalars().all()
        job_ids = [int(job.id) for job in jobs]
        if not job_ids:
            raise SystemExit(f"来源对象没有启用的同步任务: {CLUE_PATH}")

        metric_ids = {code: int(by_code[code].id) for code in CODES}
        deal_config = by_code[CODES[1]].measures or {}
        filters = deal_config.get("row_filters") or []
        if not any(
            isinstance(item, dict)
            and str(item.get("field")) == "deal"
            and str(item.get("value")) == "1"
            for item in filters
        ):
            raise SystemExit("STF-43 仍不是 deal=1 口径，请先执行 seed_crm_person_metrics.py")
        if not deal_config.get("use_latest_batch_only"):
            raise SystemExit("STF-43 未开启 use_latest_batch_only，请先执行 seed_crm_person_metrics.py")

    print(f"期间 {periods[0]} ~ {periods[-1]}（{len(periods)} 个）；指标 {len(CODES)} 个；线索同步任务 {job_ids}")
    results: list[dict] = []
    failures: list[str] = []
    current_period = datetime.now().strftime("%Y-%m")

    for period in periods:
        print(f"\n=== {period} ===")
        for code in CODES:
            version, total, persons = await _latest_value(metric_ids[code], period)
            print(f"[before] {code} v{version} total={total} persons={persons}")

        if not args.no_refresh:
            # 当前月用真实时间渲染 startTime/endTime，得到真正的「今天往前 30 天」；
            # 历史期间才传 period，按该期间 1 日渲染（与既有回补口径一致）。
            for job in jobs:
                print(f"[sync] {job.id} {job.name}")
                if period == current_period:
                    await execute_meta_sync_job(int(job.id))
                else:
                    await execute_meta_sync_job(int(job.id), period_value=period)

        rows = await _latest_clue_rows(job_ids, period)
        expected_total, expected_deal = _count(rows)
        print(f"[batch] rows={len(rows)} counted_total={expected_total} deal=1={expected_deal}")
        if not rows:
            message = f"{period}: 没有可用的线索批次，请去掉 --no-refresh 重跑"
            print(f"[failed] {message}")
            failures.append(message)
            results.append({"period": period, "failed": [message]})
            continue

        for code in CODES:
            summary = await execute_metric_calc(metric_id=metric_ids[code], period_value=period)
            print(f"[calc] {code} v{summary['calc_version']} total={summary['total']}")

        actual: dict[str, float] = {}
        for code in CODES:
            version, total, persons = await _latest_value(metric_ids[code], period)
            actual[code] = float(total or 0)
            print(f"[after]  {code} v{version} total={total} persons={persons}")

        period_failures: list[str] = []
        if round(actual[CODES[0]], 4) != float(expected_total):
            period_failures.append(f"STF-42 合计 {actual[CODES[0]]} != 批次线索数 {expected_total}")
        if round(actual[CODES[1]], 4) != float(expected_deal):
            period_failures.append(f"STF-43 合计 {actual[CODES[1]]} != 批次 deal=1 数 {expected_deal}")
        expected_rate = round(expected_deal / expected_total * 100, 4) if expected_total else 0.0
        if round(actual[CODES[2]], 4) != expected_rate:
            period_failures.append(
                f"STF-44 合计 {actual[CODES[2]]} != {expected_deal}/{expected_total} = {expected_rate}"
            )

        results.append(
            {
                "period": period,
                "batch_total": expected_total,
                "batch_deal": expected_deal,
                "batch_rate": expected_rate,
                "metric_values": actual,
                "failed": period_failures,
            }
        )
        failures.extend(f"{period}: {item}" for item in period_failures)

    print("\n" + json.dumps({"periods": periods, "results": results, "failed": failures}, ensure_ascii=False))
    await async_engine.dispose()
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
