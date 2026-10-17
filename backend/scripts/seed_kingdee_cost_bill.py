"""登记金蝶「成本计算单」（``CB_CostCalBill``）为来源对象 + 每日同步任务。

用途：
1. **PRD-06 实际单位成本**：按 CRM 订单号关联成本计算单，取本期完工的单位成本平均值
   （``FCompleteQty > 0`` 的行，用 ``FProductUseCost``）；
2. **PRD-05 BOM版本**：``FBOMNUMBERFIELD_FNUMBER``。

参数（2026-10-16 实测打通）：核算组织 ``100`` / 会计政策 ``KJZC01_SYS`` /
核算体系 ``KJHSTX01_SYS`` / 显示方式 ``2`` / 币别 ``PRE001``；按月期间取数
（``FYear``/``FPeriod``），组织 100 单月约 16,255 行。

用法：
    python scripts/seed_kingdee_cost_bill.py
    python scripts/run_meta_sync.py --name "金蝶成本计算单-产品线" --period 2026-07,2026-08,2026-09 --show-latest
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
from app.modules.erp.kingdee.model import KingdeeConnectionModel  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel, SourceSystemModel  # noqa: E402
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SOURCE_SYSTEM_CODE = "kingdee"
OBJECT_CODE = "CB_CostCalBill"
OBJECT_NAME = "成本计算单"
JOB_NAME = "金蝶成本计算单-产品线"
ORG_CODE = "100"  # 成本计算在主体组织；101~113 均返回 0 行

FIELD_KEYS = (
    "FYearPeriod,FOrderBillNo,FPRODUCTNO,FPRODUCTID_FNUMBER,FPRODUCTID_FNAME,"
    "FBOMNUMBERFIELD_FNUMBER,FPlanQty,FCompleteQty,FProductUseCost,FCompleteAmount,"
    "FSumProductUseCost,FBASICUNITFIELD_FNAME"
)

REQUEST_PARAMS: dict = {
    "Limit": 10000,
    "Model": {
        "FACCTGSYSTEMID": {"FNumber": "KJHSTX01_SYS"},
        "FACCTGORGID": {"FNumber": "{{org_code}}"},
        "FACCTPOLICYID": {"FNumber": "KJZC01_SYS"},
        "FYear": "{{year}}",
        "FEndYear": "{{year}}",
        "FPeriod": "{{month}}",
        "FEndPeriod": "{{month}}",
        "FCurrencyID": {"FNumber": "PRE001"},
        "FISSHOWDETAIL": "false",
        "FISSHOWMATERIA": "false",
        "FSHOWWAY": "2",
        "FShowIndirectExpenseDetial": "false",
        "FNOINCOMPNOSHOW": "false",
        "FSumPeriod": "false",
    },
    "SchemeId": "",
    "StartRow": 0,
    "FieldKeys": FIELD_KEYS,
    "FilterString": [],
    "IsVerifyBaseDataField": "true",
}

VARIABLES = [
    {"name": "year", "value": "now.strftime('%Y')", "value_type": "expression", "description": "当前年份"},
    {"name": "month", "value": "now.strftime('%m')", "value_type": "expression", "description": "当前月份"},
    {"name": "org_code", "value": "org_code", "value_type": "expression", "description": "任务组织编码"},
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


async def main() -> None:
    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(KingdeeConnectionModel).where(KingdeeConnectionModel.status == 0))
        ).scalars().first()
        if connection is None:
            raise SystemExit("未找到启用的金蝶连接，请先配置 erp_kingdee_connection")

        system = await get_or_create(
            db,
            SourceSystemModel,
            {"code": SOURCE_SYSTEM_CODE},
            {"name": "金蝶云星空", "connector_type": "kingdee", "connection_id": connection.id, "status": 0},
        )
        system.connection_id = connection.id

        source_object = await get_or_create(
            db,
            SourceObjectModel,
            {"system_id": system.id, "code": OBJECT_CODE},
            {
                "name": OBJECT_NAME,
                "query_type": "sys_report",
                "request_template": REQUEST_PARAMS,
                "variables": VARIABLES,
                "status": 0,
            },
        )
        source_object.name = OBJECT_NAME
        source_object.query_type = "sys_report"
        source_object.request_template = REQUEST_PARAMS
        source_object.variables = VARIABLES
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
        job.org_code = ORG_CODE
        job.cron_expr = "0 0 2 * * ?"
        job.request_params = REQUEST_PARAMS
        job.variables = VARIABLES
        job.sync_mode = "full"
        job.status = 0
        job.description = (
            "金蝶成本计算单 CB_CostCalBill（按月期间，组织 100，显示方式 2）；"
            "供产品线 PRD-05 BOM版本、PRD-06 实际单位成本取数"
        )
        await db.flush()
        register_meta_sync_job(job)
        print(
            f"来源对象 id={source_object.id}（{OBJECT_CODE}，sys_report）；"
            f"同步任务 id={job.id}（{JOB_NAME}，{job.cron_expr}，org={ORG_CODE}）"
        )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
