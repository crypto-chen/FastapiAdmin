"""初始化「产品线分析」模块（标准实体 + 字段 + 菜单 + 角色授权）。

字段定义见 ``app/modules/product/fields.py``（PRD-xx，对应财务底稿），
菜单挂在「指标中心」下，与「指标结果」「订单全链路」「客户分析」同级。

用法：
    python scripts/seed_product_module.py
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
from app.modules.metadata.model import StandardEntityModel, StandardFieldModel  # noqa: E402
from app.modules.product.fields import FIELD_DEFS  # noqa: E402
from app.modules.system.menu.model import MenuModel  # noqa: E402
from app.modules.system.role.model import RoleMenusModel, RoleModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

ENTITY_CODE = "product_line_analysis"
ENTITY_NAME = "产品线分析"
TABLE_NAME = "dwd_product_line_analysis"

MENU_PARENT_NAME = "指标中心"
MENU_NAME = "产品线分析"
MENU_ORDER = 4
BUTTONS = [
    ("产品线分析查询", "module_product:value:query", 1),
    ("产品线分析构建", "module_product:def:run", 2),
]


async def get_or_create(db, model, match: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == value for key, value in match.items()]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**match, **(defaults or {})})
        db.add(obj)
        await db.flush()
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    return obj


async def seed_entity(db) -> StandardEntityModel:
    entity = (
        await db.execute(select(StandardEntityModel).where(StandardEntityModel.code == ENTITY_CODE))
    ).scalars().first()
    if entity is None:
        entity = StandardEntityModel(code=ENTITY_CODE)
        db.add(entity)
    entity.name = ENTITY_NAME
    entity.table_name = TABLE_NAME
    entity.status = 0
    entity.description = (
        "产品线分析宽表：一行一「产品线大类 × SKU」一期间（PRD-00 ~ PRD-44），可变字段放 extra JSON"
    )
    await db.flush()
    return entity


async def seed_standard_fields(db, entity) -> dict[str, StandardFieldModel]:
    fields: dict[str, StandardFieldModel] = {}
    valid_codes = {item[0] for item in FIELD_DEFS}
    for field_code, field_name, data_type, _group, _sensitive, _source, _status, _note in FIELD_DEFS:
        row = (
            await db.execute(
                select(StandardFieldModel).where(
                    StandardFieldModel.entity_id == entity.id,
                    StandardFieldModel.field_code == field_code,
                )
            )
        ).scalars().first()
        if row is None:
            row = StandardFieldModel(entity_id=entity.id, field_code=field_code)
            db.add(row)
        row.field_name = field_name
        row.data_type = data_type
        row.excel_code = field_code
        row.is_dimension = data_type != "number"
        row.is_measure = data_type == "number"
        row.status = 0
        fields[field_code] = row
    # 清理已移除的字段，避免历史注册残留
    stale = (
        await db.execute(
            select(StandardFieldModel).where(
                StandardFieldModel.entity_id == entity.id,
                StandardFieldModel.field_code.not_in(valid_codes),
            )
        )
    ).scalars().all()
    for row in stale:
        await db.delete(row)
    await db.flush()
    return fields


async def seed_menu(db) -> list[int]:
    parent = (
        await db.execute(
            select(MenuModel).where(MenuModel.name == MENU_PARENT_NAME, MenuModel.parent_id.is_(None))
        )
    ).scalars().first()
    if parent is None:
        raise SystemExit(f"父菜单「{MENU_PARENT_NAME}」不存在，请先执行 scripts/seed_metric_menu.py")

    menu = await get_or_create(
        db,
        MenuModel,
        {"name": MENU_NAME, "parent_id": parent.id},
        {
            "type": 2,
            "order": MENU_ORDER,
            "permission": "module_product:value:query",
            "route_name": "ProductLineAnalysis",
            "route_path": "product-line",
            "component_path": "module_metric/product/index",
            "status": 0,
            "title": MENU_NAME,
            "scope": "web",
        },
    )
    await db.flush()

    menu_ids = [parent.id, menu.id]
    for name, permission, order in BUTTONS:
        button = await get_or_create(
            db,
            MenuModel,
            {"name": name, "parent_id": menu.id},
            {"type": 3, "order": order, "permission": permission, "status": 0, "scope": "web"},
        )
        await db.flush()
        menu_ids.append(button.id)
    return menu_ids


async def main() -> None:
    async with async_db_session() as db, db.begin():
        entity = await seed_entity(db)
        fields = await seed_standard_fields(db, entity)
        menu_ids = await seed_menu(db)
        roles = (
            await db.execute(select(RoleModel).where(RoleModel.code.in_(["SUPER_ADMIN", "ADMIN"])))
        ).scalars().all()
        bound = 0
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
                    bound += 1
        print(
            f"标准实体 id={entity.id}（{ENTITY_CODE}），字段 {len(fields)} 个；"
            f"菜单 id={menu_ids}，新增角色授权 {bound} 条"
        )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
