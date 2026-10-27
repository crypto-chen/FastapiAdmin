"""初始化 CRM 字典同步（产品系列/型号 + 基础分类）。

目的：订单全链路里的 ``product_model``（型号ID）与 ``product_series``（系列ID）都是编码，
同步这两张字典后就能在宽表里展示**名称**：

- ``/hs/product/getProductCategory``   → 产品系列：``id`` / ``pid`` / ``name``
- ``/hs/product/getProductModel``      → 产品型号：``id`` / ``category_id`` / ``model`` / 宽高长
- ``/hs/base/getBaseCategoryList``     → 基础分类：订单的 ``source``（店铺）与
  ``source_platform``（平台）都是这张表的 ``id``，用它映射成名称

两个接口都是**无参数、不分页的全量快照**，按周同步即可（与客户列表同节奏）。

用法：
    python scripts/seed_crm_product_dict.py
    python scripts/seed_crm_product_dict.py --connection-name "CRM 默认连接"
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.crm.client import DEFAULT_BASE_URL  # noqa: E402
from app.modules.crm.model import CrmConnectionModel  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    SourceObjectModel,
    SourceSystemModel,
)
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SOURCE_SYSTEM_CODE = "crm"
DICT_CRON = "0 0 0 * * ?;0 0 7 * * ?;0 0 12 * * ?;0 0 18 * * ?"

OBJECTS = [
    {"code": "/hs/product/getProductCategory", "name": "CRM 产品系列字典"},
    {"code": "/hs/product/getProductModel", "name": "CRM 产品型号字典"},
    {"code": "/hs/base/getBaseCategoryList", "name": "CRM 基础分类字典（店铺/平台）"},
]


async def get_or_create(db, model, match: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == value for key, value in match.items()]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**match, **(defaults or {})})
        db.add(obj)
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 CRM 产品系列/型号字典同步")
    parser.add_argument("--connection-name", default="CRM 默认连接", help="CRM 连接名称")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="CRM 域名")
    args = parser.parse_args()

    job_ids: list[int] = []
    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(
                select(CrmConnectionModel).where(CrmConnectionModel.name == args.connection_name)
            )
        ).scalars().first()
        if connection is None:
            connection = CrmConnectionModel(name=args.connection_name, base_url=args.base_url, status=0)
            db.add(connection)
            await db.flush()

        system = await get_or_create(
            db,
            SourceSystemModel,
            {"code": SOURCE_SYSTEM_CODE},
            {"name": "CRM", "connector_type": "crm", "connection_id": connection.id, "status": 0},
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        for spec in OBJECTS:
            source_object = await get_or_create(
                db,
                SourceObjectModel,
                {"system_id": system.id, "code": spec["code"]},
                {
                    "name": spec["name"],
                    "query_type": "api",
                    "request_template": {},
                    "variables": [],
                    "status": 0,
                },
            )
            source_object.name = spec["name"]
            job = (
                await db.execute(
                    select(MetaSyncJobModel)
                    .where(
                        (MetaSyncJobModel.name == spec["name"])
                        | (MetaSyncJobModel.source_object_id == source_object.id)
                    )
                    .order_by(MetaSyncJobModel.id.asc())
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=spec["name"])
                db.add(job)
            job.name = spec["name"]
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.standard_entity_id = None
            job.org_code = None
            job.cron_expr = DICT_CRON
            job.request_params = {}
            job.sync_mode = "full"
            job.status = 0
            job.description = "CRM 产品字典（无参数全量快照），按周同步"
            await db.flush()
            job_ids.append(int(job.id))
            print(f"来源对象 id={source_object.id} code={spec['code']}，同步任务 id={job.id}")

    for job_id in job_ids:
        async with async_db_session() as db:
            job = await db.get(MetaSyncJobModel, job_id)
        if job is not None:
            register_meta_sync_job(job)
    await async_engine.dispose()
    print("CRM 产品字典同步初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
