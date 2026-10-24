"""检查零售推送数据、菜单、角色和回放任务是否落在当前环境数据库。

用法::

    cd backend
    ENVIRONMENT=prod python scripts/check_retail_data.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.setting import settings  # noqa: E402
from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel  # noqa: E402
from app.modules.retail.model import RetailOrderItemModel, RetailOrderModel, RetailSyncBatchModel  # noqa: E402
from app.modules.retail.service import DEFAULT_RETAIL_PUSH_JOB_NAME  # noqa: E402
from app.modules.system.menu.model import MenuModel  # noqa: E402
from app.modules.system.role.model import RoleMenusModel, RoleModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    print(f"ENVIRONMENT={settings.ENVIRONMENT} DATABASE={settings.DATABASE_TYPE}/{settings.DATABASE_NAME}")
    async with async_db_session() as db:
        order_count = (await db.execute(select(func.count(RetailOrderModel.id)))).scalar() or 0
        item_count = (await db.execute(select(func.count(RetailOrderItemModel.id)))).scalar() or 0
        batch_count = (await db.execute(select(func.count(RetailSyncBatchModel.id)))).scalar() or 0
        periods = (
            await db.execute(
                select(RetailOrderModel.period_value)
                .distinct()
                .order_by(RetailOrderModel.period_value.desc())
            )
        ).scalars().all()
        print(f"ORDERS={order_count} ITEMS={item_count} BATCHES={batch_count} PERIODS={list(periods)}")

        rows = (
            await db.execute(
                select(RetailOrderModel)
                .order_by(RetailOrderModel.id.desc())
                .limit(5)
            )
        ).scalars().all()
        for row in rows:
            print(
                f"  id={row.id} period={row.period_value} shop_id={row.shop_id} "
                f"shop={row.shop_name} so_id={row.so_id} status={row.status}"
            )

        menu = (
            await db.execute(select(MenuModel).where(MenuModel.name == "零售订单同步"))
        ).scalars().first()
        if menu is None:
            print("MENU=MISSING（执行 ENVIRONMENT=prod python scripts/seed_retail_menu.py）")
        else:
            roles = (
                await db.execute(
                    select(RoleModel.code)
                    .join(RoleMenusModel, RoleMenusModel.role_id == RoleModel.id)
                    .where(RoleMenusModel.menu_id == menu.id)
                )
            ).scalars().all()
            print(f"MENU=id:{menu.id} status:{menu.status} permission:{menu.permission} roles:{list(roles)}")

        job = (
            await db.execute(
                select(MetaSyncJobModel).where(MetaSyncJobModel.name == DEFAULT_RETAIL_PUSH_JOB_NAME)
            )
        ).scalars().first()
        print(
            "PUSH_JOB="
            + (f"id:{job.id} status:{job.status}" if job is not None else "MISSING（执行 seed_retail_push_job.py）")
        )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
