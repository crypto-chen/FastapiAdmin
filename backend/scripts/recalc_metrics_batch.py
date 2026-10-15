"""批量重算指定指标（口径调整后回填历史期间用）。

用法：
    python scripts/recalc_metrics_batch.py --code marketing_travel_expense --code marketing_vehicle_expense
    python scripts/recalc_metrics_batch.py --code-file scripts/metric_groups/expense_caliber.txt
    python scripts/recalc_metrics_batch.py --code-file scripts/metric_groups/expense_caliber.txt --with-dependents
    python scripts/recalc_metrics_batch.py --code marketing_total_expense --period 2026-09
    python scripts/recalc_metrics_batch.py --code marketing_total_expense --period-from 2026-01 --period-to 2026-10
    python scripts/recalc_metrics_batch.py --code marketing_total_expense --log recalc.log

期间三种写法：``--period``（可重复，精确指定）、``--period-from/--period-to``（闭区间，按已有期间过滤）、
都不传时按已有同步批次的全部期间依次重算。
指标写法：``--code``（可重复）或 ``--code-file``（每行一个编码，``#`` 开头为注释）；
加 ``--with-dependents`` 会自动把依赖这些指标的汇总/比率指标一并加入，并按依赖顺序执行。
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.engine import execute_metric_calc  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.modules.metadata.model import MetaSyncRunModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def available_periods() -> list[str]:
    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(MetaSyncRunModel.period_value)
                .where(MetaSyncRunModel.status == "success", MetaSyncRunModel.period_value.isnot(None))
                .group_by(MetaSyncRunModel.period_value)
                .order_by(MetaSyncRunModel.period_value.asc())
            )
        ).scalars().all()
    return [str(item) for item in rows]


async def metric_ids(codes: list[str]) -> list[tuple[int, str]]:
    async with async_db_session() as db:
        rows = (
            await db.execute(select(MetricDefModel.id, MetricDefModel.code).where(MetricDefModel.code.in_(codes)))
        ).all()
    found = {code: int(mid) for mid, code in rows}
    missing = [code for code in codes if code not in found]
    for code in missing:
        print(f"跳过（指标不存在）: {code}")
    return [(found[code], code) for code in codes if code in found]


def read_codes_from_file(path: str) -> list[str]:
    """从文本文件读取指标编码（每行一个，``#`` 开头为注释）。"""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [text.strip() for text in lines if text.strip() and not text.strip().startswith("#")]


async def with_dependents(codes: list[str]) -> list[str]:
    """把依赖这些指标的汇总/比率指标一并补齐，返回按依赖顺序（被依赖者在前）的编码列表。"""
    async with async_db_session() as db:
        rows = (await db.execute(select(MetricDefModel.code, MetricDefModel.measures))).all()
    depends: dict[str, set[str]] = {}
    for code, measures in rows:
        config = json.loads(measures) if isinstance(measures, str) else (measures or {})
        used: set[str] = set()
        for key in ("component_metric_codes", "numerator_metric_codes", "denominator_metric_codes"):
            used |= {str(item) for item in (config.get(key) or [])}
        depends[str(code)] = used

    ordered: list[str] = []
    seen: set[str] = set()
    layer = [code for code in codes if code not in seen]
    while layer:
        for code in layer:
            if code not in seen:
                seen.add(code)
                ordered.append(code)
        layer = [code for code, deps in depends.items() if code not in seen and (deps & set(layer))]
    return ordered


async def main() -> None:
    parser = argparse.ArgumentParser(description="批量重算指标")
    parser.add_argument("--code", action="append", default=None, help="指标编码，可重复")
    parser.add_argument("--code-file", default=None, help="指标编码清单文件（每行一个，支持 # 注释）")
    parser.add_argument("--with-dependents", action="store_true", help="同时纳入依赖这些指标的汇总/比率指标")
    parser.add_argument("--period", action="append", default=None, help="期间值，可重复；缺省为全部已有期间")
    parser.add_argument("--period-from", default=None, help="起始期间（含），如 2026-01")
    parser.add_argument("--period-to", default=None, help="结束期间（含），如 2026-10")
    parser.add_argument("--log", default=None, help="同时写入日志文件")
    args = parser.parse_args()

    codes = list(args.code or [])
    if args.code_file:
        codes += read_codes_from_file(args.code_file)
    seen: set[str] = set()
    codes = [code for code in codes if not (code in seen or seen.add(code))]
    if not codes:
        raise SystemExit("请用 --code 或 --code-file 指定指标编码")
    if args.with_dependents:
        codes = await with_dependents(codes)

    if args.period:
        periods = list(args.period)
    else:
        periods = await available_periods()
        if args.period_from:
            periods = [item for item in periods if item >= args.period_from]
        if args.period_to:
            periods = [item for item in periods if item <= args.period_to]
    if not periods:
        raise SystemExit("没有匹配的期间，请检查 --period / --period-from / --period-to")
    plan = await metric_ids(codes)
    print(f"期间 {len(periods)} 个，指标 {len(plan)} 个，共 {len(periods) * len(plan)} 次计算", flush=True)

    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None

    def emit(line: str) -> None:
        print(line, flush=True)
        if log_handle:
            log_handle.write(line + "\n")
            log_handle.flush()

    for period in periods:
        for metric_id, code in plan:
            started = time.time()
            try:
                summary = await execute_metric_calc(metric_id=metric_id, period_value=period)
                emit(f"{period} {code} -> {summary['total']} ({time.time() - started:.1f}s)")
            except Exception as e:  # noqa: BLE001
                emit(f"{period} {code} -> ERROR {type(e).__name__}: {e}")
        emit(f"=== {period} 完成 ===")

    if log_handle:
        log_handle.close()
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
