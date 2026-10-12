"""初始化「生产订单」来源对象与同步任务（金蝶 ``PRD_MO`` → 订单全链路分析底表）。

背景：订单全链路分析需要把 CRM 订单（``orderAnalyze.number``）与生产侧打通。
金蝶生产订单分录上的 ``FSaleOrderNo``（需求单据）就是 CRM 订单号，因此同步
``PRD_MO`` 后可用「CRM 订单号」串起接单 → 下推 → 生产 → 入库 → 出货。

同步范围：

- 单据头 + ``FTreeEntity`` 分录一起取（单据查询按分录返回，表头字段在每行重复）；
- 过滤：已审核 ``FDocumentStatus='C'``、单据日期 ``FDate`` 落在本期（月起 ~ 月末闭区间）；
- 每天 02:00 取本月（早于指标调度 02:30），历史月份用
  ``execute_meta_sync_job(job_id, 'YYYY-MM')`` 逐月回补，次月 1 日强制重拉上月。

字段已用 ``scripts/kingdee_bill_probe.py --form-id PRD_MO`` 实测可取；分录字段
**不需要**加 ``FTreeEntity_`` 前缀。

用法：
    python scripts/seed_kingdee_production_order.py
"""

import asyncio
import configparser
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INI_PATH = PROJECT_ROOT / "env" / "kindee_conf.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.kingdee.model import KingdeeConnectionModel  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    FieldMappingModel,
    MetaSyncJobModel,
    SourceFieldModel,
    SourceObjectModel,
    SourceSystemModel,
    StandardEntityModel,
    StandardFieldModel,
)
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CONNECTION_NAME = "金蝶默认连接"
SOURCE_SYSTEM_CODE = "kingdee"
SOURCE_OBJECT_CODE = "PRD_MO"
SOURCE_OBJECT_NAME = "生产订单"
STANDARD_ENTITY_CODE = "production_order"
STANDARD_ENTITY_NAME = "生产订单"
STANDARD_TABLE_NAME = "dwd_production_order"
SYNC_JOB_NAME = "生产订单-订单全链路"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

# (字段Key, 中文名, 数据类型)：表头字段 + FTreeEntity 分录字段，顺序即 FieldKeys 顺序
SOURCE_FIELDS = [
    # 单据头
    ("FBillNo", "生产订单号", "string"),
    ("FDate", "单据日期", "date"),
    ("FDocumentStatus", "单据状态", "string"),
    ("FPrdOrgId.FNumber", "生产组织编码", "string"),
    ("F_UIVG_Decimal_83g", "Y订单金额", "number"),
    ("F_UIVG_Base_re5.FNumber", "Y销售员编码", "string"),
    ("F_UIVG_Assistant_re5.FNumber", "Y销售订单类型", "string"),
    ("F_NTHM_Text_qtr", "完工状态", "string"),
    ("F_NTHM_Datetime_ca9", "完工时间", "date"),
    ("F_NTHM_PRONO", "排程编号", "string"),
    # 明细 FTreeEntity
    ("FMaterialId.FNumber", "物料编码", "string"),
    ("FMaterialName", "物料名称", "string"),
    ("FSpecification", "规格型号", "string"),
    ("FQty", "生产数量", "number"),
    ("FPlanStartDate", "计划开工时间", "date"),
    ("FPlanFinishDate", "计划完工时间", "date"),
    ("FSaleOrderNo", "需求单据(CRM订单号)", "string"),
    ("FStatus", "业务状态", "string"),
    ("FStartDate", "开工日期", "date"),
    ("FFinishDate", "完工日期", "date"),
    ("FCloseDate", "结案日期", "date"),
    ("FStockInQuaQty", "合格品入库数量", "number"),
    ("F_NTHM_Remarks_jhrq", "交货日期", "date"),
    ("F_UIVG_Base_w5c.FNUMBER", "Y成品编码", "string"),
    ("F_UIVG_Text_fg2", "Y成品型号", "string"),
    ("F_UIVG_Date_83g", "Y入库日期", "date"),
    ("F_UIVG_Decimal_qtr", "Y入库数量（保存）", "number"),
]
PRIMARY_KEY = "FBillNo"

# 期间变量：{{ month_start }} / {{ month_end }} 由元数据同步任务渲染
# （回补历史期间时用该期间 1 日渲染，见 metadata/sync.py 的 resolve_period_datetime）
OBJECT_VARIABLES = [
    {
        "name": "month_start",
        "value_type": "expression",
        "value": "now.replace(day=1).strftime('%Y-%m-%d')",
        "description": "本期首日",
    },
    {
        "name": "month_end",
        "value_type": "expression",
        "value": "((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')",
        "description": "本期末日",
    },
]

REQUEST_PARAMS = {
    "FormId": SOURCE_OBJECT_CODE,
    "FieldKeys": ",".join(field_key for field_key, _name, _type in SOURCE_FIELDS),
    "FilterString": "FDocumentStatus='C' and FDate>='{{month_start}}' and FDate<='{{month_end}}'",
    "OrderString": "FBillNo",
    "TopRowCount": 0,
}

JOB_DESCRIPTION = (
    "生产订单（ExecuteBillQuery，含 FTreeEntity 分录）：已审核、按单据日期取本期；"
    "FSaleOrderNo 为 CRM 订单号，用于订单全链路关联"
)


async def get_or_create(db, model, match_keys: list[str], values: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == values[key] for key in match_keys if key in values]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**(defaults or {}), **values})
        db.add(obj)
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def main() -> None:
    conf = configparser.ConfigParser()
    conf.read(INI_PATH, encoding="utf-8")

    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(
                select(KingdeeConnectionModel).where(KingdeeConnectionModel.name == CONNECTION_NAME)
            )
        ).scalars().first()
        if connection is None:
            connection = KingdeeConnectionModel(
                name=CONNECTION_NAME,
                server_url=conf.get("config", "x-kdapi-serverurl", fallback=""),
                acct_id=conf.get("config", "x-kdapi-acctid", fallback=""),
                username=conf.get("config", "x-kdapi-username", fallback=""),
                app_id=conf.get("config", "x-kdapi-appid", fallback=""),
                app_secret=CryptoUtil.encrypt(conf.get("config", "x-kdapi-appsec", fallback="")),
                lcid=conf.getint("config", "x-kdapi-lcid", fallback=2052),
                org_num=conf.getint("config", "x-kdapi-orgnum", fallback=0),
                connect_timeout=conf.getint("config", "x-kdapi-connecttimeout", fallback=120),
                request_timeout=conf.getint("config", "x-kdapi-requesttimeout", fallback=120),
                status=0,
            )
            db.add(connection)
            await db.flush()

        system = await get_or_create(
            db,
            SourceSystemModel,
            ["code"],
            {"code": SOURCE_SYSTEM_CODE, "name": "金蝶云星空", "connector_type": "kingdee"},
            {"connection_id": connection.id, "status": 0},
        )
        system.connection_id = connection.id

        source_object = await get_or_create(
            db,
            SourceObjectModel,
            ["system_id", "code"],
            {"system_id": system.id, "code": SOURCE_OBJECT_CODE},
            {
                "name": SOURCE_OBJECT_NAME,
                "query_type": "bill_query",
                "request_template": REQUEST_PARAMS,
                "variables": OBJECT_VARIABLES,
                "status": 0,
            },
        )
        source_object.name = SOURCE_OBJECT_NAME
        source_object.query_type = "bill_query"
        source_object.request_template = REQUEST_PARAMS
        source_object.variables = OBJECT_VARIABLES

        standard_entity = await get_or_create(
            db,
            StandardEntityModel,
            ["code"],
            {"code": STANDARD_ENTITY_CODE},
            {"name": STANDARD_ENTITY_NAME, "table_name": STANDARD_TABLE_NAME, "status": 0},
        )

        for field_key, field_name, data_type in SOURCE_FIELDS:
            is_measure = data_type == "number"
            source_field = await get_or_create(
                db,
                SourceFieldModel,
                ["object_id", "field_key"],
                {"object_id": source_object.id, "field_key": field_key},
                {
                    "field_name": field_name,
                    "data_type": data_type,
                    "is_primary_key": field_key == PRIMARY_KEY,
                    "is_watermark": False,
                    "status": 0,
                },
            )
            standard_field = await get_or_create(
                db,
                StandardFieldModel,
                ["entity_id", "field_code"],
                {"entity_id": standard_entity.id, "field_code": field_key},
                {
                    "field_name": field_name,
                    "data_type": data_type,
                    "is_dimension": not is_measure,
                    "is_measure": is_measure,
                    "status": 0,
                },
            )
            exists_mapping = (
                await db.execute(
                    select(FieldMappingModel).where(
                        FieldMappingModel.source_field_id == source_field.id,
                        FieldMappingModel.standard_field_id == standard_field.id,
                    )
                )
            ).scalars().first()
            if exists_mapping is None:
                db.add(
                    FieldMappingModel(
                        source_object_id=source_object.id,
                        source_field_id=source_field.id,
                        standard_field_id=standard_field.id,
                        transform_type="direct",
                        order=0,
                        status=0,
                    )
                )

        job = (
            await db.execute(
                select(MetaSyncJobModel)
                .where(
                    (MetaSyncJobModel.name == SYNC_JOB_NAME)
                    | (MetaSyncJobModel.source_object_id == source_object.id)
                )
                .order_by(MetaSyncJobModel.id.asc())
            )
        ).scalars().first()
        if job is None:
            job = MetaSyncJobModel(name=SYNC_JOB_NAME)
            db.add(job)
        job.name = SYNC_JOB_NAME
        job.source_system_id = system.id
        job.source_object_id = source_object.id
        job.standard_entity_id = standard_entity.id
        job.org_code = None
        job.cron_expr = SYNC_CRON
        job.request_params = REQUEST_PARAMS
        job.sync_mode = "full"
        job.status = 0
        job.description = JOB_DESCRIPTION
        await db.flush()
        job_id = job.id

        print(
            f"金蝶连接 id={connection.id}，来源系统 id={system.id}，"
            f"来源对象 id={source_object.id}，标准实体 id={standard_entity.id}，同步任务 id={job_id}"
        )
        print(f"字段数={len(SOURCE_FIELDS)}，过滤={REQUEST_PARAMS['FilterString']}")

    job = await _load_job(job_id)
    if job is not None:
        register_meta_sync_job(job)
    await async_engine.dispose()
    print("生产订单同步初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
