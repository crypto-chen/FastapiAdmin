"""校验 TM-01/TM-02 指标结果（按指标编码查找，不依赖数据库自增 ID）。

用法（项目根目录）：
    python deploy/wecom-opcenter-20261112/verify.py
    python deploy/wecom-opcenter-20261112/verify.py --period 2026-10
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.engine import execute_metric_calc  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CODES = ("TM-01", "TM-02")


async def main() -> None:
    parser = argparse.ArgumentParser(description="校验运营中心工时指标")
    parser.add_argument(
        "--period",
        action="append",
        default=None,
        help="期间，可重复；默认 2026-09/10/11",
    )
    args = parser.parse_args()
    periods = args.period or ["2026-09", "2026-10", "2026-11"]

    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(MetricDefModel.id, MetricDefModel.code).where(
                    MetricDefModel.code.in_(CODES)
                )
            )
        ).all()
    found = {code: int(mid) for mid, code in rows}
    missing = [code for code in CODES if code not in found]
    if missing:
        raise SystemExit(
            f"指标不存在，请先执行 seed_opcenter_worktime_metrics.py: {missing}"
        )

    for period in periods:
        for code in CODES:
            summary = await execute_metric_calc(found[code], period)
            print(
                f"{code} {period} total={summary.get('total')} "
                f"version={summary.get('calc_version')}"
            )

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
