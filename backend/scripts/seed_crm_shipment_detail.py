"""接入 CRM「发货明细」接口（``/hs/shipments/getShipmentsDetail``）。

用途：产品线分析的 **PRD-11 出货数量** 取这接口（发货时间 ``send_time`` 口径，
另有 ``/hs/order/orderShipments`` 是审核日期口径，两者并存）。

注册内容：
1. 来源对象 ``/hs/shipments/getShipmentsDetail``（query_type=api，按期间渲染 dateRange）；
2. 同步任务（每日 02:00 拉当月，可手工按期间回补）。

接口文档见 ``docs/发货明细接口文档.md``；返回每张发货单一行：
``send_qty / type / order_id / qty / price / product_model``（未分页，单月约 1.2~1.5k 行）。

用法：
    python scripts/seed_crm_shipment_detail.py
    python scripts/run_meta_sync.py --name "CRM发货明细-getShipmentsDetail" --period 2026-07,2026-08,2026-09
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
from app.modules.crm.model import CrmConnectionModel  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel, SourceSystemModel  # noqa: E402
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SOURCE_SYSTEM_CODE = "crm"
OBJECT_CODE = "/hs/shipments/getShipmentsDetail"
OBJECT_NAME = "CRM 发货明细（发货时间口径）"
JOB_NAME = "CRM发货明细-getShipmentsDetail"

# 按期间渲染成 [期初, 期末]；today 由回补期间覆盖，保证历史期回补正确
REQUEST_TEMPLATE: dict = {
    "dateRange": [
        "{{ today.replace(day=1) }}",
        "{{ (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1) }}",
    ],
}


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


async def main() -> None:
    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(CrmConnectionModel).where(CrmConnectionModel.status == 0))
        ).scalars().first()
        if connection is None:
            raise SystemExit("未找到启用的 CRM 连接，请先配置 crm_connection")

        system = await get_or_create(
            db,
            SourceSystemModel,
            {"code": SOURCE_SYSTEM_CODE},
            {"name": "CRM", "connector_type": "crm", "connection_id": connection.id, "status": 0},
        )
        system.connection_id = connection.id

        source_object = await get_or_create(
            db,
            SourceObjectModel,
            {"system_id": system.id, "code": OBJECT_CODE},
            {
                "name": OBJECT_NAME,
                "query_type": "api",
                "request_template": REQUEST_TEMPLATE,
                "status": 0,
            },
        )
        source_object.request_template = REQUEST_TEMPLATE
        source_object.name = OBJECT_NAME
        source_object.query_type = "api"
        source_object.status = 0
        await db.flush()

        job = (
            await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.name == JOB_NAME))
        ).scalars().first()
        if job is None:
            job = MetaSyncJobModel(name=JOB_NAME)
            db.add(job)
        job.source_system_id = system.id
        job.source_object_id = source_object.id
        job.cron_expr = "0 0 2 * * ?;0 20 12 * * ?;0 20 18 * * ?"
        job.request_params = REQUEST_TEMPLATE
        job.sync_mode = "full"
        job.status = 0
        job.description = (
            "CRM 接口 /hs/shipments/getShipmentsDetail（发货时间口径，未分页，单月约 1.2~1.5k 行）；"
            "供产品线 PRD-11 出货数量取数"
        )
        await db.flush()
        register_meta_sync_job(job)
        print(
            f"来源对象 id={source_object.id}（{OBJECT_CODE}）；同步任务 id={job.id}（{JOB_NAME}，{job.cron_expr}）"
        )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
