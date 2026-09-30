"""按期间重算全部启用指标（先按依赖分层，可先重拉该期间取数批次）。

用法：
    python scripts/run_all_metric_calc.py --period 2026-09
    python scripts/run_all_metric_calc.py --period 2026-09 --refresh
    python scripts/run_all_metric_calc.py --period 2026-09 --code marketing_office_expense

``--refresh`` 会先把该期间所有同步任务的取数批次重新拉一遍（金蝶报表/单据、聚水潭、
CRM 接口），再执行指标计算；不带该参数时直接复用数据库里已有的期间批次。
实时取数类指标（账龄计提）本身不落同步批次，计算时按组织实时取数，不受该开关影响。

计算顺序由 ``app.modules.metric.batch`` 按 ``measures`` 里声明的依赖分层决定：
组成指标所在层先执行，依赖它的派生指标后执行，同层并发。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.metric.batch import run_metric_batch  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

# CLI 场景只保留控制台输出：默认的日志文件被运行中的后端服务占用，且 DEBUG 级别过于啰嗦
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="按期间重算全部启用指标")
    parser.add_argument("--period", required=True, help="期间值，如 2026-09")
    parser.add_argument("--code", action="append", default=None, help="只重算指定指标编码，可重复")
    parser.add_argument("--refresh", action="store_true", help="重算前先重拉该期间的同步批次")
    args = parser.parse_args()

    try:
        summary = await run_metric_batch(
            period_value=args.period,
            codes=args.code,
            refresh=args.refresh,
            label=f"期间 {args.period}",
        )
    except ValueError as e:
        raise SystemExit(str(e)) from e
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
