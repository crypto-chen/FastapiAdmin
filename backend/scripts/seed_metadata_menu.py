"""初始化元数据管理菜单。

用法：
    python scripts/seed_metadata_menu.py
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


async def get_or_create(db, **kwargs) -> MenuModel:
    obj = (await db.execute(select(MenuModel).where(*[getattr(MenuModel, key) == value for key, value in kwargs.items()]))).scalars().first()
    if obj is None:
        obj = MenuModel(**kwargs)
        db.add(obj)
        await db.flush()
    return obj


async def main() -> None:
    async with async_db_session() as db, db.begin():
        parent = await get_or_create(
            db,
            name="元数据管理",
            type=1,
            order=8,
            icon="ri:database-2-line",
            route_name="Metadata",
            route_path="/metadata",
            redirect="/metadata/index",
            status=0,
            title="元数据管理",
            scope="web",
        )
        child = await get_or_create(
            db,
            name="元数据配置",
            type=2,
            order=1,
            permission="module_metadata:source:query",
            route_name="MetadataIndex",
            route_path="index",
            component_path="module_metadata/index",
            parent_id=parent.id,
            status=0,
            title="元数据配置",
            scope="web",
        )
        view_child = await get_or_create(
            db,
            name="元数据查看",
            type=2,
            order=2,
            permission="module_metadata:view:query",
            route_name="MetadataView",
            route_path="view",
            component_path="module_metadata_view/index",
            parent_id=parent.id,
            status=0,
            title="元数据查看",
            scope="web",
        )
        permissions = [
            ("新增", "module_metadata:source:create", 1),
            ("编辑", "module_metadata:source:update", 2),
            ("删除", "module_metadata:source:delete", 3),
            ("标准查询", "module_metadata:standard:query", 4),
            ("标准新增", "module_metadata:standard:create", 5),
            ("标准编辑", "module_metadata:standard:update", 6),
            ("标准删除", "module_metadata:standard:delete", 7),
            ("映射查询", "module_metadata:mapping:query", 8),
            ("映射新增", "module_metadata:mapping:create", 9),
            ("映射编辑", "module_metadata:mapping:update", 10),
            ("映射删除", "module_metadata:mapping:delete", 11),
            ("同步查询", "module_metadata:sync:query", 12),
            ("同步新增", "module_metadata:sync:create", 13),
            ("同步编辑", "module_metadata:sync:update", 14),
            ("同步删除", "module_metadata:sync:delete", 15),
            ("指标查询", "module_metric:def:query", 16),
            ("指标新增", "module_metric:def:create", 17),
            ("指标编辑", "module_metric:def:update", 18),
            ("指标删除", "module_metric:def:delete", 19),
        ]
        button_ids: list[int] = []
        for name, perm, order in permissions:
            button = await get_or_create(
                db,
                name=name,
                type=3,
                order=order,
                permission=perm,
                parent_id=child.id,
                status=0,
                scope="web",
            )
            button_ids.append(button.id)

        roles = (await db.execute(select(RoleModel).where(RoleModel.code.in_(["SUPER_ADMIN", "ADMIN"])))).scalars().all()
        all_menu_ids = sorted({parent.id, child.id, view_child.id, *button_ids})
        for role in roles:
            for menu_id in all_menu_ids:
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
    print("元数据管理菜单初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
