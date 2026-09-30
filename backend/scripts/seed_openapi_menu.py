"""初始化「开放接口」菜单（接入应用 + 调用日志 + 按钮权限）。

用法：
    python scripts/seed_openapi_menu.py
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


async def get_or_create(db, name: str, parent_id: int | None, **kwargs) -> MenuModel:
    """按「名称 + 上级」幂等创建菜单，避免重复执行时产生重复节点。"""
    parent_condition = MenuModel.parent_id == parent_id if parent_id else MenuModel.parent_id.is_(None)
    conditions = [MenuModel.name == name, parent_condition]
    obj = (await db.execute(select(MenuModel).where(*conditions))).scalars().first()
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
            "开放接口",
            None,
            type=1,
            order=10,
            icon="ri:plug-line",
            route_name="OpenApi",
            route_path="/openapi",
            redirect="/openapi/client",
            status=0,
            title="开放接口",
            scope="web",
        )
        client_menu = await get_or_create(
            db,
            "接入应用",
            parent.id,
            type=2,
            order=1,
            permission="module_openapi:client:query",
            route_name="OpenApiClient",
            route_path="client",
            component_path="module_openapi/client/index",
            status=0,
            title="接入应用",
            scope="web",
        )
        log_menu = await get_or_create(
            db,
            "调用日志",
            parent.id,
            type=2,
            order=2,
            permission="module_openapi:log:query",
            route_name="OpenApiLog",
            route_path="log",
            component_path="module_openapi/log/index",
            status=0,
            title="调用日志",
            scope="web",
        )

        menu_ids = [parent.id, client_menu.id, log_menu.id]
        for name, permission, order, parent_menu in [
            ("接入应用查询", "module_openapi:client:query", 1, client_menu),
            ("接入应用新增", "module_openapi:client:create", 2, client_menu),
            ("接入应用修改", "module_openapi:client:update", 3, client_menu),
            ("接入应用删除", "module_openapi:client:delete", 4, client_menu),
            ("调用日志查询", "module_openapi:log:query", 1, log_menu),
        ]:
            button = await get_or_create(
                db,
                name,
                parent_menu.id,
                type=3,
                order=order,
                permission=permission,
                status=0,
                scope="web",
            )
            menu_ids.append(button.id)

        roles = (await db.execute(select(RoleModel).where(RoleModel.code.in_(["SUPER_ADMIN", "ADMIN"])))).scalars().all()
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
    await async_engine.dispose()
    print("开放接口菜单初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
