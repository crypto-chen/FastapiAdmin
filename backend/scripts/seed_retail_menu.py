"""初始化「零售订单同步」菜单与权限。

菜单挂在「开放接口」下；页面包含「零售订单」与「推送批次」两个页签。

用法::

    python scripts/seed_retail_menu.py
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

PARENT_NAME = "开放接口"
MENU_NAME = "零售订单同步"
MENU_PERMISSION = "module_retail:order:query"


async def get_or_create(db, name: str, parent_id: int | None, **kwargs) -> MenuModel:
    parent_condition = MenuModel.parent_id == parent_id if parent_id else MenuModel.parent_id.is_(None)
    obj = (
        await db.execute(
            select(MenuModel).where(MenuModel.name == name, parent_condition)
        )
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
        parent = (
            await db.execute(
                select(MenuModel).where(MenuModel.name == PARENT_NAME, MenuModel.parent_id.is_(None))
            )
        ).scalars().first()
        if parent is None:
            parent = await get_or_create(
                db,
                PARENT_NAME,
                None,
                type=1,
                order=10,
                icon="ri:plug-line",
                route_name="OpenApi",
                route_path="/openapi",
                redirect="/openapi/client",
                status=0,
                title=PARENT_NAME,
                scope="web",
            )

        menu = await get_or_create(
            db,
            MENU_NAME,
            parent.id,
            type=2,
            order=3,
            permission=MENU_PERMISSION,
            route_name="RetailOrderSync",
            route_path="retail",
            component_path="module_retail/order/index",
            status=0,
            title=MENU_NAME,
            scope="web",
        )

        menu_ids = [parent.id, menu.id]
        for name, permission, order in (
            ("零售订单查询", "module_retail:order:query", 1),
            ("推送批次查询", "module_retail:batch:query", 2),
            ("零售店铺同步", "module_retail:shop:sync", 3),
        ):
            button = await get_or_create(
                db,
                name,
                menu.id,
                type=3,
                order=order,
                permission=permission,
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

        print(f"零售订单菜单 id={menu.id}，权限 {MENU_PERMISSION} / module_retail:batch:query")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
