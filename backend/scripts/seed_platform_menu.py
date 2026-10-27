"""初始化「指标中心 → 平台分析」菜单与权限。

页面：``frontend/web/src/views/module_metric/platform/index.vue``
权限：``module_metric:platform:query``

用法::

    cd backend
    python scripts/seed_platform_menu.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.system.menu.model import MenuModel  # noqa: E402
from app.modules.system.role.model import RoleMenusModel, RoleModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

PARENT_NAME = "指标中心"
MENU_NAME = "平台分析"
MENU_PERMISSION = "module_metric:platform:query"


async def get_or_create(db, name: str, parent_id: int | None, **kwargs) -> MenuModel:
    """按「名称 + 上级」幂等创建菜单。"""
    parent_condition = MenuModel.parent_id == parent_id if parent_id else MenuModel.parent_id.is_(None)
    obj = (
        await db.execute(select(MenuModel).where(MenuModel.name == name, parent_condition))
    ).scalars().first()
    if obj is None:
        obj = MenuModel(name=name, parent_id=parent_id, **kwargs)
        db.add(obj)
        await db.flush()
    else:
        for key, value in kwargs.items():
            setattr(obj, key, value)
    return obj


async def main() -> None:
    async with async_db_session() as db, db.begin():
        parent = await get_or_create(
            db,
            PARENT_NAME,
            None,
            type=1,
            order=9,
            icon="ri:bar-chart-box-line",
            route_name="Metric",
            route_path="/metric",
            redirect="/metric/value",
            status=0,
            title=PARENT_NAME,
            scope="web",
        )

        menu = await get_or_create(
            db,
            MENU_NAME,
            parent.id,
            type=2,
            order=5,
            permission=MENU_PERMISSION,
            route_name="MetricPlatformAnalysis",
            route_path="platform",
            component_path="module_metric/platform/index",
            status=0,
            title=MENU_NAME,
            scope="web",
        )

        menu_ids = [parent.id, menu.id]
        button = await get_or_create(
            db,
            "平台分析查询",
            menu.id,
            type=3,
            order=1,
            permission=MENU_PERMISSION,
            status=0,
            scope="web",
        )
        menu_ids.append(button.id)

        roles = (
            await db.execute(select(RoleModel).where(RoleModel.code.in_(["SUPER_ADMIN", "ADMIN"])))
        ).scalars().all()
        for role in roles:
            for menu_id in sorted(set(menu_ids)):
                exists = (
                    await db.execute(
                        select(RoleMenusModel).where(
                            RoleMenusModel.role_id == role.id,
                            RoleMenusModel.menu_id == menu_id,
                        )
                    )
                ).scalars().first()
                if exists is None:
                    db.add(RoleMenusModel(role_id=role.id, menu_id=menu_id))

        print(f"平台分析菜单 id={menu.id}，权限 {MENU_PERMISSION}（已绑定 SUPER_ADMIN/ADMIN）")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
