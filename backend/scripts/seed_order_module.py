"""初始化订单全链路：标准实体/字段/来源映射 + 菜单 + 权限。

内容：

1. 标准实体 ``order_full_chain`` 与全部字段（来自 ``app/modules/order/fields.py``）；
2. CRM 订单对象的来源字段（新旧字段名都注册，便于对照）与来源映射，
   ``transform_config`` 里带 ``priority``（越小越优先）—— 换来源只改这里；
3. 菜单「订单全链路」（挂在指标中心 → 指标结果 下面）+ 查询/构建按钮；
4. 绑定 SUPER_ADMIN / ADMIN 角色。

用法：
    python scripts/seed_order_module.py
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
from app.modules.metadata.model import (  # noqa: E402
    FieldMappingModel,
    SourceFieldModel,
    SourceObjectModel,
    StandardEntityModel,
    StandardFieldModel,
)
from app.modules.order.fields import (  # noqa: E402
    DATETIME_KEYS,
    FIELD_DEFS,
    INTAKE_KEYS_DOMESTIC,
    INTAKE_KEYS_EXPORT,
    MATERIAL_COST_KEYS,
    PROCESS_COST_KEYS,
    SOURCE_KEYS,
)
from app.modules.system.menu.model import MenuModel  # noqa: E402
from app.modules.system.role.model import RoleMenusModel, RoleModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

ENTITY_CODE = "order_full_chain"
ENTITY_NAME = "订单全链路"
TABLE_NAME = "dwd_order_full_chain"

ORDER_OBJECTS = ["/hs/order/orderAnalyze?type=1", "/hs/order/orderAnalyze?type=2"]

MENU_PARENT_NAME = "指标中心"
MENU_NAME = "订单全链路"
MENU_ORDER = 2  # 排在「指标结果」后面
BUTTONS = [
    ("订单全链路查询", "module_order:value:query", 1),
    ("订单全链路构建", "module_order:def:run", 2),
]


def collect_source_keys() -> dict[str, list[str]]:
    """字段编码 → 来源候选键（按优先级）。"""
    mapping: dict[str, list[str]] = {}
    for field_code, keys in SOURCE_KEYS.items():
        mapping[field_code] = list(keys)
    mapping["intake_untaxed"] = [*INTAKE_KEYS_DOMESTIC, *INTAKE_KEYS_EXPORT]
    mapping["unit_cost"] = [*MATERIAL_COST_KEYS, *PROCESS_COST_KEYS]
    mapping["material_cost_unit"] = list(MATERIAL_COST_KEYS)
    mapping["total_cost"] = [*MATERIAL_COST_KEYS, *PROCESS_COST_KEYS]
    for field_code, keys in DATETIME_KEYS.items():
        mapping[field_code] = list(keys)
    mapping["order_date"] = ["createtime"]
    mapping["design_service_income"] = ["design_remove_taxes_freight", "design_cost"]
    return mapping


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
    entity.description = "订单全链路宽表：一行一单（订单号维度），可变字段放 extra JSON"
    await db.flush()
    return entity


async def seed_standard_fields(db, entity) -> dict[str, StandardFieldModel]:
    fields: dict[str, StandardFieldModel] = {}
    for field_code, field_name, data_type, _group, _sensitive, excel_code in FIELD_DEFS:
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
        row.excel_code = excel_code or None
        row.is_dimension = data_type != "number"
        row.is_measure = data_type == "number"
        row.status = 0
        fields[field_code] = row
    await db.flush()
    return fields


async def seed_mappings(db, standard_fields: dict[str, StandardFieldModel]) -> tuple[int, int]:
    """注册来源字段与映射（按优先级）。"""
    objects = (
        await db.execute(select(SourceObjectModel).where(SourceObjectModel.code.in_(ORDER_OBJECTS)))
    ).scalars().all()
    if not objects:
        return 0, 0

    source_keys = collect_source_keys()
    # 归一化：一个来源字段只注册一次
    need_keys: dict[str, str] = {}
    for field_code, keys in source_keys.items():
        for key in keys:
            need_keys.setdefault(key, field_code)

    source_field_ids: dict[tuple[int, str], int] = {}
    created_fields = 0
    for obj in objects:
        for key in need_keys:
            row = (
                await db.execute(
                    select(SourceFieldModel).where(
                        SourceFieldModel.object_id == obj.id,
                        SourceFieldModel.field_key == key,
                    )
                )
            ).scalars().first()
            if row is None:
                row = SourceFieldModel(
                    object_id=obj.id,
                    field_key=key,
                    field_name=key,
                    data_type="string",
                    is_primary_key=False,
                    is_watermark=False,
                    status=0,
                )
                db.add(row)
                await db.flush()
                created_fields += 1
            source_field_ids[(obj.id, key)] = row.id

    created_mappings = 0
    for field_code, keys in source_keys.items():
        standard = standard_fields.get(field_code)
        if standard is None:
            continue
        for priority, key in enumerate(keys, start=1):
            for obj in objects:
                source_field_id = source_field_ids.get((obj.id, key))
                if source_field_id is None:
                    continue
                exists = (
                    await db.execute(
                        select(FieldMappingModel).where(
                            FieldMappingModel.source_field_id == source_field_id,
                            FieldMappingModel.standard_field_id == standard.id,
                        )
                    )
                ).scalars().first()
                if exists is not None:
                    continue
                db.add(
                    FieldMappingModel(
                        source_object_id=obj.id,
                        source_field_id=source_field_id,
                        standard_field_id=standard.id,
                        transform_type="direct",
                        transform_config={
                            "source_object_code": obj.code,
                            "source_field": key,
                            "priority": priority,
                            "role": "primary" if priority == 1 else "fallback",
                            "effective_from": "2026-10" if key in {"amount", "material_cost_total", "process_cost_total"} else None,
                        },
                        order=priority,
                        status=0,
                    )
                )
                created_mappings += 1
    await db.flush()
    return created_fields, created_mappings


async def seed_menu(db) -> list[int]:
    parent = (
        await db.execute(select(MenuModel).where(MenuModel.name == MENU_PARENT_NAME, MenuModel.parent_id.is_(None)))
    ).scalars().first()
    if parent is None:
        raise SystemExit(f"父菜单「{MENU_PARENT_NAME}」不存在，请先执行 scripts/seed_metric_menu.py")

    menu = (
        await db.execute(
            select(MenuModel).where(MenuModel.name == MENU_NAME, MenuModel.parent_id == parent.id)
        )
    ).scalars().first()
    if menu is None:
        menu = MenuModel(name=MENU_NAME, parent_id=parent.id)
        db.add(menu)
    menu.type = 2
    menu.order = MENU_ORDER
    menu.permission = "module_order:value:query"
    menu.route_name = "OrderFullChain"
    menu.route_path = "order"
    menu.component_path = "module_metric/order/index"
    menu.status = 0
    menu.title = MENU_NAME
    menu.scope = "web"
    await db.flush()

    menu_ids = [parent.id, menu.id]
    for name, permission, order in BUTTONS:
        button = (
            await db.execute(select(MenuModel).where(MenuModel.name == name, MenuModel.parent_id == menu.id))
        ).scalars().first()
        if button is None:
            button = MenuModel(name=name, parent_id=menu.id)
            db.add(button)
        button.type = 3
        button.order = order
        button.permission = permission
        button.status = 0
        button.scope = "web"
        await db.flush()
        menu_ids.append(button.id)
    return menu_ids


async def main() -> None:
    async with async_db_session() as db, db.begin():
        entity = await seed_entity(db)
        standard_fields = await seed_standard_fields(db, entity)
        created_fields, created_mappings = await seed_mappings(db, standard_fields)
        menu_ids = await seed_menu(db)

        roles = (await db.execute(select(RoleModel).where(RoleModel.code.in_(["SUPER_ADMIN", "ADMIN"])))).scalars().all()
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
            f"标准实体 id={entity.id}，字段 {len(standard_fields)} 个；"
            f"新增来源字段 {created_fields} 个、映射 {created_mappings} 条；"
            f"菜单 id={menu_ids}，角色绑定 {bound} 条"
        )
    await async_engine.dispose()
    print("订单全链路元数据与菜单初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
