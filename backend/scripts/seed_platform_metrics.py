"""初始化/恢复平台分析默认指标（platform_metric_def）。

幂等：按 code upsert，不删除自定义指标。
新增指标也可以直接在管理端「指标中心 → 平台分析 → 指标配置」里加，不需要跑脚本。

用法::

    cd backend
    python scripts/seed_platform_metrics.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.platform.service import PlatformAnalysisService  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    async with async_db_session() as db, db.begin():
        result = await PlatformAnalysisService(db).reset_defaults()
        total = (
            await PlatformAnalysisService(db).configs(only_enabled=False)
        )
    await async_engine.dispose()
    print(
        f"平台指标初始化完成：默认 {result['total']} 个（新增 {result['created']}，"
        f"更新 {result['updated']}），当前表内 {len(total)} 个"
    )


if __name__ == "__main__":
    asyncio.run(main())
