"""检查零售订单菜单是否已注册到当前环境数据库。

用法::

    cd backend
    ENVIRONMENT=prod python scripts/check_retail_menu.py
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
from app.modules.system.menu.model import MenuModel  # noqa: E402
from app.modules.system.role.model import RoleMenusModel, RoleModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

MENU_NAME = "零售订单同步"


async def main() -> None:
    print(f"ENVIRONMENT={settings.ENVIRONMENT} DATABASE={settings.DATABASE_TYPE}/{settings.DATABASE_NAME}")
    async with async_db_session() as db:
        menu = (
            await db.execute(select(MenuModel).where(MenuModel.name == MENU_NAME))
        ).scalars().first()
        if menu is None:
            print(f"MISSING: 当前库没有「{MENU_NAME}」菜单")
            print("执行：ENVIRONMENT=prod python scripts/seed_retail_menu.py")
            return
        print(
            f"FOUND: id={menu.id} parent_id={menu.parent_id} status={menu.status} "
            f"permission={menu.permission} component={menu.component_path}"
        )
        role_rows = (
            await db.execute(
                select(RoleModel.code)
                .join(RoleMenusModel, RoleMenusModel.role_id == RoleModel.id)
                .where(RoleMenusModel.menu_id == menu.id)
            )
        ).scalars().all()
        print("BOUND_ROLES=" + (",".join(role_rows) if role_rows else "NONE"))
        if not role_rows:
            print("当前角色未绑定：请在「系统管理 → 角色 → 菜单权限」勾选，或重跑 seed_retail_menu.py")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
