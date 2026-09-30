"""手动重算指标（按期间 / 按组织）。

用法：
    python scripts/run_metric_calc.py --code marketing_office_expense
    python scripts/run_metric_calc.py --code marketing_office_expense --period 2026-09 --org 100
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.engine import execute_metric_calc  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    parser = argparse.ArgumentParser(description="手动重算指标")
    parser.add_argument("--code", required=True, help="指标编码")
    parser.add_argument("--period", default=None, help="期间值，如 2026-09")
    parser.add_argument("--org", action="append", default=None, help="组织编码，可重复；缺省为全部组织")
    args = parser.parse_args()

    async with async_db_session() as db:
        metric = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code == args.code))
        ).scalars().first()
        if metric is None:
            raise SystemExit(f"指标不存在: {args.code}")
        metric_id = metric.id

    summary = await execute_metric_calc(metric_id=metric_id, period_value=args.period, org_codes=args.org)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
