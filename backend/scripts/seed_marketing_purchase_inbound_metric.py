"""初始化「当期营销中心采购入库金额（含税）」指标。

口径（用户给定，改口径只改本文件的 ``COMPONENTS``）：

**当期营销中心采购入库金额（含税） = 采购入库单（标准采购入库）价税合计（本位币）合计
 + 收料通知单（费用承担部门不含人力行政部）价税合计合计**

1. **采购入库单**（金蝶 ``STK_InStock``，``ExecuteBillQuery``）：
   已审核（``FDocumentStatus='C'``）、入库日期落在本期，单据类型为**标准采购入库**
   （``FBillTypeID.FNumber = RKD01_SYS``，名称为「标准采购入库」）的单据，
   取**表头价税合计（本位币）** ``FBillAllAmount_LC`` 合计。
   单据查询按分录返回、表头金额在同单多条分录上重复，故按 ``FBillNo`` 去重后只计一次。

2. **收料通知单**（金蝶 ``PUR_ReceiveBill``，``ExecuteBillQuery``）：
   已审核、收料日期落在本期，**费用承担部门**（行字段 ``F_NTHM_Base_re5``）名称
   **不含「人力行政部」**的分录，取**分录价税合计** ``FAllAmount`` 合计。
   费用承担部门是分录级字段，故按分录过滤、按分录金额汇总（空部门视为不含人力行政部，纳入）。

结果口径：公司整体（不分组织/部门），月指标；同步任务每天 02:00 取本期单据
（早于指标调度的 02:30），月指标每日重算当月，次月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_marketing_purchase_inbound_metric.py

依赖：金蝶连接（``env/kindee_conf.ini`` 或库中「金蝶默认连接」）。
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
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CONNECTION_NAME = "金蝶默认连接"
SOURCE_SYSTEM_CODE = "kingdee"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

METRIC_CODE = "marketing_purchase_inbound_incl_tax"
METRIC_NAME = "当期营销中心采购入库金额（含税）"

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


def _request_params(source_object_code: str, field_keys: list[str]) -> dict:
    return {
        "FormId": source_object_code,
        "FieldKeys": ",".join(field_keys),
        "FilterString": "FDocumentStatus='C' and FDate>='{{month_start}}' and FDate<='{{month_end}}'",
        "OrderString": "FBillNo",
        "TopRowCount": 0,
    }


# 每个来源对象：编码 / 名称 / 标准实体 / 字段清单（字段顺序即单据查询返回值顺序）
SOURCES = [
    {
        "code": "STK_InStock",
        "name": "采购入库单",
        "entity_code": "purchase_instock",
        "entity_name": "采购入库单",
        "table_name": "dwd_purchase_instock",
        "job_name": "采购入库单-营销中心采购入库金额(含税)",
        "fields": [
            ("FBillNo", "单据编号", True),
            ("FDate", "入库日期", False),
            ("FBillTypeID.FNumber", "单据类型编码", False),
            ("FBillTypeID.FName", "单据类型名称", False),
            ("FDocumentStatus", "单据状态", False),
            ("FStockOrgId.FNumber", "收料组织编码", False),
            ("FBillAllAmount_LC", "价税合计(本位币)", False),
        ],
        "measure_field_keys": {"FBillAllAmount_LC"},
        "job_desc": "采购入库单（ExecuteBillQuery）：已审核、按入库日期取本期单据，不分组织",
    },
    {
        "code": "PUR_ReceiveBill",
        "name": "收料通知单",
        "entity_code": "receive_bill",
        "entity_name": "收料通知单",
        "table_name": "dwd_receive_bill",
        "job_name": "收料通知单-营销中心采购入库金额(含税)",
        "fields": [
            ("FBillNo", "单据编号", True),
            ("FDate", "收料日期", False),
            ("FBillTypeID.FNumber", "单据类型编码", False),
            ("FBillTypeID.FName", "单据类型名称", False),
            ("FDocumentStatus", "单据状态", False),
            ("FStockOrgId.FNumber", "收料组织编码", False),
            ("FBillAllAmount", "价税合计", False),
            ("F_NTHM_Base_re5.FNumber", "费用承担部门编码", False),
            ("F_NTHM_Base_re5.FName", "费用承担部门名称", False),
            ("FAllAmount", "分录价税合计", False),
        ],
        "measure_field_keys": {"FAllAmount"},
        "job_desc": "收料通知单（ExecuteBillQuery）：已审核、按收料日期取本期单据，不分组织",
    },
]

# 取数规则：由指标计算引擎解释（kind=bill_amount_filter，多来源组成一个合计）
MEASURES = {
    "kind": "bill_amount_filter",
    "components": [
        {
            "source_object_code": "STK_InStock",
            "label": "采购入库单（标准采购入库，价税合计本位币）",
            # 表头价税合计(本位币)：单据按分录返回，必须按单号去重，否则按分录条数翻倍
            "amount_field": "FBillAllAmount_LC",
            "dedupe_field": "FBillNo",
            "row_filters": [
                {"field": "FBillTypeID.FNumber", "op": "equals", "value": "RKD01_SYS"}
            ],
        },
        {
            "source_object_code": "PUR_ReceiveBill",
            "label": "收料通知单（费用承担部门不含人力行政部，分录价税合计）",
            # 费用承担部门是分录级字段：按分录过滤，取分录价税合计；空部门视为不含人力行政部
            "amount_field": "FAllAmount",
            "row_filters": [
                {"field": "F_NTHM_Base_re5.FName", "op": "not_contains", "value": "人力行政部"}
            ],
        },
    ],
}
DIMENSIONS = {"org": False, "dept": False}

FORMULA = (
    "SUM(采购入库单.FBillAllAmount_LC WHERE 单据类型=标准采购入库(RKD01_SYS) 按单号去重) "
    "+ SUM(收料通知单.FAllAmount WHERE 费用承担部门 NOT LIKE '%人力行政部%')；"
    "均限本期已审核单据"
)
DESCRIPTION = (
    "当期营销中心采购入库金额（含税）：采购入库单（金蝶 STK_InStock）中单据类型为「标准采购入库」"
    "（FBillTypeID.FNumber=RKD01_SYS）的已审核单据，取表头价税合计（本位币）FBillAllAmount_LC 并按单号去重；"
    "加上收料通知单（金蝶 PUR_ReceiveBill）中费用承担部门（分录字段 F_NTHM_Base_re5.FName）不含「人力行政部」"
    "的分录价税合计 FAllAmount；两项均限本期（按入库/收料日期）已审核单据。"
    "公司整体口径（不分组织/部门）。月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，"
    "每次计算保留 calc_version 版本。"
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
    job_ids: list[int] = []

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
        )
        system.connection_id = connection.id

        for source in SOURCES:
            field_keys = [key for key, _name, _pk in source["fields"]]
            request_params = _request_params(source["code"], field_keys)
            source_object = await get_or_create(
                db,
                SourceObjectModel,
                ["system_id", "code"],
                {"system_id": system.id, "code": source["code"]},
                {
                    "name": source["name"],
                    "query_type": "bill_query",
                    "request_template": request_params,
                    "variables": OBJECT_VARIABLES,
                    "status": 0,
                },
            )
            source_object.query_type = "bill_query"
            source_object.request_template = request_params
            source_object.variables = OBJECT_VARIABLES

            standard_entity = await get_or_create(
                db,
                StandardEntityModel,
                ["code"],
                {"code": source["entity_code"]},
                {"name": source["entity_name"], "table_name": source["table_name"], "status": 0},
            )

            for field_key, field_name, is_pk in source["fields"]:
                is_measure = field_key in source["measure_field_keys"]
                source_field = await get_or_create(
                    db,
                    SourceFieldModel,
                    ["object_id", "field_key"],
                    {"object_id": source_object.id, "field_key": field_key},
                    {
                        "field_name": field_name,
                        "data_type": "number" if is_measure else "string",
                        "is_primary_key": is_pk,
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
                        "data_type": "number" if is_measure else "string",
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
                        (MetaSyncJobModel.name == source["job_name"])
                        | (MetaSyncJobModel.source_object_id == source_object.id)
                    )
                    .order_by(MetaSyncJobModel.id.asc())
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=source["job_name"])
                db.add(job)
            job.name = source["job_name"]
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.standard_entity_id = standard_entity.id
            job.org_code = None
            job.cron_expr = SYNC_CRON
            job.request_params = request_params
            job.sync_mode = "full"
            job.status = 0
            job.description = source["job_desc"]
            await db.flush()
            job_ids.append(job.id)
            print(f"来源对象 id={source_object.id} code={source['code']}，同步任务 id={job.id}")

        metric = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code == METRIC_CODE))
        ).scalars().first()
        if metric is None:
            metric = MetricDefModel(code=METRIC_CODE)
            db.add(metric)
        metric.name = METRIC_NAME
        metric.period_type = "month"
        metric.sensitivity = 0
        metric.formula = FORMULA
        metric.dimensions = DIMENSIONS
        metric.measures = MEASURES
        metric.source_entity_id = None  # 多来源对象，不挂单个标准实体
        metric.status = 0
        metric.description = DESCRIPTION
        await db.flush()
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    for job_id in job_ids:
        job = await _load_job(job_id)
        if job is not None:
            register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心采购入库金额（含税）指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
