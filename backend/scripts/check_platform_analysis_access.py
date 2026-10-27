"""打印开放应用及「平台渠道分析」开关状态，便于上线后确认谁已开通。

用法::

    cd backend
    python scripts/check_platform_analysis_access.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.setting import settings  # noqa: E402
from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.openapi.model import OpenClientModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    print(f"ENVIRONMENT={settings.ENVIRONMENT} DATABASE={settings.DATABASE_TYPE}/{settings.DATABASE_NAME}")
    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(OpenClientModel).order_by(OpenClientModel.id.asc())
            )
        ).scalars().all()
        if not rows:
            print("暂无开放应用（在「系统管理 → 开放接口应用」创建）")
        allowed = 0
        for row in rows:
            flag = "YES" if row.allow_platform_analysis else "NO"
            allowed += 1 if row.allow_platform_analysis else 0
            print(
                f"id={row.id} app_id={row.app_id} name={row.name} "
                f"status={row.status} 平台渠道分析={flag}"
            )
        print(f"合计 {len(rows)} 个应用，其中已开通平台渠道分析 {allowed} 个")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
