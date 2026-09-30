"""初始化「指标中心」菜单（指标结果查看页 + 计算按钮权限）。

用法：
    python scripts/seed_metric_menu.py
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
            "指标中心",
            None,
            type=1,
            order=9,
            icon="ri:bar-chart-box-line",
            route_name="Metric",
            route_path="/metric",
            redirect="/metric/value",
            status=0,
            title="指标中心",
            scope="web",
        )
        child = await get_or_create(
            db,
            "指标结果",
            parent.id,
            type=2,
            order=1,
            permission="module_metric:value:query",
            route_name="MetricValue",
            route_path="value",
            component_path="module_metric/value/index",
            status=0,
            title="指标结果",
            scope="web",
        )

        menu_ids = [parent.id, child.id]
        for name, permission, order in [
            ("指标结果查询", "module_metric:value:query", 1),
            ("指标重算", "module_metric:def:run", 2),
            ("指标定义查询", "module_metric:def:query", 3),
        ]:
            button = await get_or_create(
                db,
                name,
                child.id,
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
    print("指标中心菜单初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
