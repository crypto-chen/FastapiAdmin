"""删除「指标中心 → 平台分析」菜单及其角色绑定（幂等）。

用法::

    cd backend
    python ../deploy/platform-metric-page-20261027/rollback_menu.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, select

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.system.menu.model import MenuModel  # noqa: E402
from app.modules.system.role.model import RoleMenusModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

MENU_NAME = "平台分析"


async def main() -> None:
    async with async_db_session() as db, db.begin():
        menus = (
            await db.execute(select(MenuModel).where(MenuModel.name == MENU_NAME))
        ).scalars().all()
        if not menus:
            print("未找到「平台分析」菜单，无需回滚")
            await async_engine.dispose()
            return
        ids = [menu.id for menu in menus]
        children = (
            await db.execute(select(MenuModel.id).where(MenuModel.parent_id.in_(ids)))
        ).scalars().all()
        all_ids = ids + list(children)
        await db.execute(delete(RoleMenusModel).where(RoleMenusModel.menu_id.in_(all_ids)))
        await db.execute(delete(MenuModel).where(MenuModel.id.in_(all_ids)))
        print(f"已删除菜单 {all_ids}（含子按钮）及角色绑定")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
