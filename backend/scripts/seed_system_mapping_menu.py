"""初始化系统映射管理菜单。

包含「映射配置 / 人工绑定 / 权限部门绑定 / 系统标准人员」四个页面与按钮权限，
并把菜单授予 SUPER_ADMIN、ADMIN 角色。

用法：
    python scripts/seed_system_mapping_menu.py
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
            name="系统映射管理",
            type=1,
            order=9,
            icon="ri:route-line",
            route_name="SystemMappingParent",
            route_path="/system-mapping",
            redirect="/system-mapping/index",
            status=0,
            title="系统映射管理",
            scope="web",
        )
        child = await get_or_create(
            db,
            name="映射配置",
            type=2,
            order=1,
            permission="module_mapping:org:query",
            route_name="SystemMapping",
            route_path="index",
            component_path="module_system_mapping/index",
            parent_id=parent.id,
            status=0,
            title="映射配置",
            scope="web",
        )
        bind_child = await get_or_create(
            db,
            name="人工绑定",
            type=2,
            order=2,
            permission="module_mapping:bind:query",
            route_name="SystemMappingBind",
            route_path="bind",
            component_path="module_manual_binding/index",
            parent_id=parent.id,
            status=0,
            title="人工绑定",
            scope="web",
        )
        sys_dept_child = await get_or_create(
            db,
            name="权限部门绑定",
            type=2,
            order=3,
            permission="module_mapping:bind:query",
            route_name="SysDeptBinding",
            route_path="permission-dept",
            component_path="module_sys_dept_binding/index",
            parent_id=parent.id,
            status=0,
            title="权限部门绑定",
            scope="web",
        )
        # 内部标准人员（master_person）维护页：权限走 masterdata 模块
        person_child = await get_or_create(
            db,
            name="系统标准人员",
            type=2,
            order=4,
            permission="module_masterdata:person:query",
            route_name="SystemMappingPerson",
            route_path="standard-person",
            component_path="module_masterdata/person/index",
            parent_id=parent.id,
            status=0,
            title="系统标准人员",
            scope="web",
        )

        permissions = [
            ("新增", "module_mapping:dept:create", 1),
            ("编辑", "module_mapping:dept:update", 2),
            ("删除", "module_mapping:dept:delete", 3),
            ("组织绑定", "module_mapping:org:create", 4),
            ("人员绑定", "module_mapping:person:create", 5),
            ("任岗绑定", "module_mapping:person:create", 6),
            ("来源类型", "module_mapping:source:query", 7),
            ("权限绑定", "module_mapping:bind:create", 8),
            # 手动同步任务按钮（无 Cron）：人员架构 / 人员
            ("同步CRM架构", "module_mapping:sync:org", 9),
            ("同步CRM人员", "module_mapping:sync:person", 10),
        ]
        menu_ids = sorted({parent.id, child.id, bind_child.id, sys_dept_child.id, person_child.id})
        for name, permission, order in permissions:
            button = await get_or_create(
                db,
                name=name,
                type=3,
                order=order,
                permission=permission,
                parent_id=child.id,
                status=0,
                scope="web",
            )
            menu_ids.append(button.id)

        # 「系统标准人员」页按钮权限
        person_permissions = [
            ("新增", "module_masterdata:person:create", 1),
            ("编辑", "module_masterdata:person:update", 2),
            ("删除", "module_masterdata:person:delete", 3),
        ]
        for name, permission, order in person_permissions:
            button = await get_or_create(
                db,
                name=name,
                type=3,
                order=order,
                permission=permission,
                parent_id=person_child.id,
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
    print("系统映射管理菜单初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
