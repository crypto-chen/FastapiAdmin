"""指标中心菜单分组工具。

菜单层级：

    指标中心
      └─ 营销业务指标
           ├─ 指标结果
           ├─ 订单全链路
           ├─ 客户分析
           ├─ 产品线分析
           └─ 平台分析

后续新增 IT 指标、财务指标、生产指标时，在「指标中心」下再建同级目录即可。
"""

from sqlalchemy import select

from app.modules.system.menu.model import MenuModel
from app.modules.system.role.model import RoleMenusModel, RoleModel

METRIC_ROOT_NAME = "指标中心"
MARKETING_GROUP_NAME = "营销业务指标"
MARKETING_GROUP_ROUTE = "marketing"
MARKETING_GROUP_ROUTE_NAME = "MetricMarketing"
MARKETING_DEFAULT_PATH = "/metric/marketing/value"


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
        await db.flush()
    return obj


async def ensure_metric_root(db) -> MenuModel:
    """确保「指标中心」一级目录存在，并把默认入口指到营销业务指标。"""
    root = await get_or_create(
        db,
        METRIC_ROOT_NAME,
        None,
        type=1,
        order=9,
        icon="ri:bar-chart-box-line",
        route_name="Metric",
        route_path="/metric",
        redirect=MARKETING_DEFAULT_PATH,
        status=0,
        title=METRIC_ROOT_NAME,
        scope="web",
    )
    root.redirect = MARKETING_DEFAULT_PATH
    await db.flush()
    return root


async def ensure_marketing_group(db) -> MenuModel:
    """确保「指标中心 → 营销业务指标」分组存在。"""
    root = await ensure_metric_root(db)
    group = await get_or_create(
        db,
        MARKETING_GROUP_NAME,
        root.id,
        type=1,
        order=1,
        icon="ri:line-chart-line",
        route_name=MARKETING_GROUP_ROUTE_NAME,
        route_path=MARKETING_GROUP_ROUTE,
        redirect=MARKETING_DEFAULT_PATH,
        status=0,
        title=MARKETING_GROUP_NAME,
        scope="web",
    )
    return group


async def move_metric_pages_to_marketing(db) -> list[int]:
    """把「指标中心」下现有的页面菜单迁到「营销业务指标」。

    只移动 type=2 的页面菜单；后续新增的 IT/财务/生产目录（type=1）不会被误移。
    返回移动过的菜单 ID。
    """
    root = await ensure_metric_root(db)
    group = await ensure_marketing_group(db)
    pages = (
        await db.execute(
            select(MenuModel).where(
                MenuModel.parent_id == root.id,
                MenuModel.type == 2,
                MenuModel.id != group.id,
            )
        )
    ).scalars().all()
    moved: list[int] = []
    for page in pages:
        page.parent_id = group.id
        moved.append(int(page.id))
    await db.flush()
    return moved


async def bind_roles(db, menu_ids: list[int]) -> None:
    """把菜单绑定到 SUPER_ADMIN / ADMIN，避免新增分组后管理员看不到。"""
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
