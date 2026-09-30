"""打印启用指标的依赖分层（不计算、只读），用于排查调度顺序问题。

用法：
    python scripts/check_metric_deps.py
    python scripts/check_metric_deps.py --code marketing_margin_of_safety_rate

输出每天 02:30 批次任务的执行顺序：第 1 层先跑、层内并发、层间串行；
末尾列出配置问题（依赖的指标不存在/未启用、依赖自身、成环）。
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
from app.modules.metric.batch import build_metric_layers, load_enabled_metrics  # noqa: E402
from app.modules.metric.engine import metric_dependency_codes  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    parser = argparse.ArgumentParser(description="打印启用指标的依赖分层")
    parser.add_argument("--code", action="append", default=None, help="只看这些指标编码，可重复")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，便于二次处理")
    args = parser.parse_args()

    metrics = await load_enabled_metrics(args.code)
    if not metrics:
        raise SystemExit("没有匹配的启用指标")
    layers, problems = build_metric_layers(metrics)

    if args.json:
        print(
            json.dumps(
                {
                    "metric_count": len(metrics),
                    "layer_count": len(layers),
                    "layers": [[item["code"] for item in layer] for layer in layers],
                    "problems": problems,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        await async_engine.dispose()
        return

    print(f"启用指标 {len(metrics)} 个，共 {len(layers)} 层（层内并发、层间串行）\n")
    for depth, layer in enumerate(layers, start=1):
        print(f"第 {depth} 层（{len(layer)} 个）")
        for item in layer:
            deps = sorted({dep for dep in metric_dependency_codes(item["measures"]) if dep != item["code"]})
            print(f"  - {item['code']}  ← {', '.join(deps) if deps else '（无指标依赖）'}")
        print()
    if problems:
        print("配置问题：")
        for problem in problems:
            print(f"  - {problem}")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
