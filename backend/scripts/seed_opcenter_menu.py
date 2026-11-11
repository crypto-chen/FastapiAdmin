"""初始化「指标中心 → 运营中心指标 → 运营中心主表指标」菜单与权限。

菜单层级：

    指标中心
      ├─ 营销业务指标
      │    └─ 指标结果
      └─ 运营中心指标
           └─ 运营中心主表指标

「运营中心主表指标」复用指标结果页组件，通过 category 只显示运营中心口径的指标。

用法：
    python scripts/seed_opcenter_menu.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from _metric_menu_utils import bind_roles, ensure_metric_root, get_or_create  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

GROUP_NAME = "运营中心指标"
PAGE_NAME = "运营中心主表指标"
PAGE_PATH = "/metric/opcenter/value"


async def main() -> None:
    async with async_db_session() as db, db.begin():
        root = await ensure_metric_root(db)
        group = await get_or_create(
            db,
            GROUP_NAME,
            root.id,
            type=1,
            order=2,
            icon="ri:pie-chart-line",
            route_name="MetricOpCenter",
            route_path="opcenter",
            redirect=PAGE_PATH,
            status=0,
            title=GROUP_NAME,
            scope="web",
        )
        page = await get_or_create(
            db,
            PAGE_NAME,
            group.id,
            type=2,
            order=1,
            permission="module_metric:value:query",
            route_name="MetricOpCenterValue",
            route_path="value",
            component_path="module_metric/opcenter/index",
            status=0,
            title=PAGE_NAME,
            scope="web",
        )

        menu_ids = [root.id, group.id, page.id]
        for name, permission, order in [
            ("运营中心指标查询", "module_metric:value:query", 1),
            ("运营中心指标重算", "module_metric:def:run", 2),
            ("运营中心指标定义查询", "module_metric:def:query", 3),
        ]:
            button = await get_or_create(
                db,
                name,
                page.id,
                type=3,
                order=order,
                permission=permission,
                status=0,
                scope="web",
            )
            menu_ids.append(button.id)

        await bind_roles(db, menu_ids)
    await async_engine.dispose()
    print("运营中心菜单初始化完成：指标中心 → 运营中心指标 → 运营中心主表指标")


if __name__ == "__main__":
    asyncio.run(main())
