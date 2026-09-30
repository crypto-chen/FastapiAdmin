"""初始化「营销中心机箱成品仓」指标（来源：金蝶《存货收发存汇总表》）。

口径（由 ``metric_def.measures`` 声明，改口径只改这里）：

1. 取 ERP100 组织（组织编码 ``100``）的《存货收发存汇总表》
   （金蝶 ``HS_INOUTSTOCKSUMMARYRPT``，``GetSysReportData`` 系统报表）；
2. 过滤条件（``request_template.Model``）：

   - 核算体系 ``KJHSTX01_SYS``、核算组织 ``{{org_code}}``、会计政策 ``KJZC01_SYS``；
   - 会计期间 = 当期年月（``{{year}}`` / ``{{period}}``）；
   - **仓库区间 = ``JXCPC`` ~ ``JXCPC``** —— 报表的「仓库」是区间（起 ~ 至），
     只填起止其一不会生效（实测会返回全部仓库），必须两端都填同一个编码才能锁定单一仓库；
     ``JXCPC`` 即「机箱成品仓」；
3. 汇总「期末结存金额 ``FENDAmount``」（明细行求和；``amount_field`` 改成 ``FENDQty`` 即数量口径）；
4. 报表同一批结果里同时返回**明细行**与**小计行**（``-总计``，仓库列为空），
   引擎按「仓库为空 / 物料编码以 ``-总计`` 结尾」跳过小计行，避免金额被重复计入一倍。

同步任务每天 02:00 取当期数据（早于指标调度的 02:30）；月指标每日重算当月，
次月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_marketing_chassis_warehouse_metric.py
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
SOURCE_OBJECT_CODE = "HS_INOUTSTOCKSUMMARYRPT"
SOURCE_OBJECT_NAME = "存货收发存汇总表"
STANDARD_ENTITY_CODE = "inventory_inout_stock_summary"
STANDARD_ENTITY_NAME = "存货收发存汇总表"
STANDARD_TABLE_NAME = "dwd_inventory_inout_stock_summary"
METRIC_CODE = "marketing_chassis_warehouse_balance"
METRIC_NAME = "营销中心机箱成品仓"
SYNC_JOB_NAME = "存货收发存汇总表-组织100"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

# 组织与仓库：ERP100 组织（编码 100）下的机箱成品仓（仓库编码 JXCPC）
ORG_CODE = "100"
WAREHOUSE_CODE = "JXCPC"
# 存货核算的核算体系 / 会计政策（取自金蝶 Org_AccountSystem / BD_AcctPolicy）
ACCT_SYSTEM_CODE = "KJHSTX01_SYS"
ACCT_POLICY_CODE = "KJZC01_SYS"

# 报表返回列（FieldKeys 的顺序即返回值的顺序；取自金蝶 WebAPI《存货收发存汇总表》字段说明）
SOURCE_FIELDS = [
    ("FMATERIALBASEID", "物料编码", False),
    ("FMATERIALNAME", "物料名称", False),
    ("FSTOCKId", "仓库", False),
    ("FSTOCKPLACENAME", "仓位", False),
    ("FACCTGRANGEID", "核算范围编码", False),
    ("FACCTGRANGENAME", "核算范围名称", False),
    ("FUNITNAME", "基本单位", False),
    ("FINITQty", "期初结存数量", True),
    ("FINITAMOUNT", "期初结存金额", True),
    ("FRECEIVEQty", "本期收入数量", True),
    ("FRECEIVEAmount", "本期收入金额", True),
    ("FSENDQty", "本期发出数量", True),
    ("FSENDAmount", "本期发出金额", True),
    ("FENDQty", "期末结存数量", True),
    ("FENDAmount", "期末结存金额", True),
]
FIELD_KEYS = [field_key for field_key, _name, _is_measure in SOURCE_FIELDS]
FIELD_NAMES = {field_key: field_name for field_key, field_name, _is_measure in SOURCE_FIELDS}
MEASURE_FIELD_KEYS = {field_key for field_key, _name, is_measure in SOURCE_FIELDS if is_measure}

# 期间变量：{{ year }} / {{ period }} 由元数据同步任务按取数期间渲染
# （回补历史期间时按该期间 1 日渲染，见 metadata/sync.py 的 resolve_period_datetime）
OBJECT_VARIABLES = [
    {"name": "year", "value_type": "expression", "value": "now.strftime('%Y')", "description": "会计年度"},
    {"name": "period", "value_type": "expression", "value": "now.strftime('%m')", "description": "会计期间"},
]

REQUEST_PARAMS = {
    "FieldKeys": ",".join(FIELD_KEYS),
    "SchemeId": "",
    "StartRow": 0,
    "Limit": 2000,
    "IsVerifyBaseDataField": "true",
    "FilterString": [],
    "Model": {
        "FACCTGSYSTEMID": {"FNumber": ACCT_SYSTEM_CODE},
        "FACCTGORGID": {"FNumber": "{{org_code}}"},
        "FACCTPOLICYID": {"FNumber": ACCT_POLICY_CODE},
        "FYear": "{{year}}",
        "FPeriod": "{{period}}",
        "FENDYEAR": "{{year}}",
        "FEndPeriod": "{{period}}",
        "FMATERIALID": {"FNumber": ""},
        "FENDMATERIALID": {"FNumber": ""},
        "FEXPENID": {"FNumber": ""},
        "FENDEXPENID": {"FNumber": ""},
        "FACCTGRANGEID": {"FNumber": ""},
        "FOwnerID": {"FNumber": ""},
        "FSTOCKORGID": {"FNumber": ""},
        # 仓库区间：起 ~ 至 必须同时填同一编码才会精确锁定该仓库
        "FSTOCKId": {"FNumber": WAREHOUSE_CODE},
        "FENDSTOCKID": {"FNumber": WAREHOUSE_CODE},
        "FMATERTYPEID": {"FNUMBER": ""},
        "FCOMBOTotalType": "",
        "FDimType": "",
        "FCHXEXPENSE": "false",
        "FCHXTotal": "false",
        "FCHXNOINOUT": "false",
        "FCHXNOCOSTALLOT": "false",
        "FIsDisplayPeriod": "false",
        "FCHXNOSTOCKADJ": "false",
        "FCOMBOSTATUS": "",
        "FCURRENCYID": {"FNumber": ""},
    },
}

# 取数规则：由指标计算引擎解释（kind=inventory_ledger_balance）
MEASURES = {
    "kind": "inventory_ledger_balance",
    "source_object_code": SOURCE_OBJECT_CODE,
    "amount_field": "FENDAmount",
    "qty_field": "FENDQty",
    "stock_field": "FSTOCKId",
    "material_field": "FMATERIALBASEID",
    "subtotal_suffix": "-总计",
    # 该报表没有部门维度
    "detail_is_department": False,
}
DIMENSIONS = {"org": True, "dept": False, "warehouse": True}

FORMULA = (
    "SUM(存货收发存汇总表.期末结存金额 FENDAmount) WHERE 核算组织=100 AND 仓库区间=JXCPC~JXCPC "
    "AND 会计期间=期间 AND 物料编码 NOT LIKE '%-总计'"
)
DESCRIPTION = (
    "营销中心机箱成品仓：取 ERP100 组织（组织编码 100）金蝶《存货收发存汇总表》"
    "（HS_INOUTSTOCKSUMMARYRPT）中仓库区间为 JXCPC~JXCPC（机箱成品仓）的期末结存金额 FENDAmount 汇总；"
    "报表同时返回明细行与小计行（-总计，仓库列为空），引擎跳过小计行，避免金额重复计入一倍；"
    "取数量口径时把 measures.amount_field 改为 FENDQty 即可。"
    "月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，每次计算保留 calc_version 版本。"
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
                "query_type": "sys_report",
                "request_template": REQUEST_PARAMS,
                "variables": OBJECT_VARIABLES,
                "status": 0,
            },
        )
        source_object.query_type = "sys_report"
        source_object.request_template = REQUEST_PARAMS
        source_object.variables = OBJECT_VARIABLES

        standard_entity = await get_or_create(
            db,
            StandardEntityModel,
            ["code"],
            {"code": STANDARD_ENTITY_CODE},
            {"name": STANDARD_ENTITY_NAME, "table_name": STANDARD_TABLE_NAME, "status": 0},
        )

        for field_key in FIELD_KEYS:
            is_measure = field_key in MEASURE_FIELD_KEYS
            source_field = await get_or_create(
                db,
                SourceFieldModel,
                ["object_id", "field_key"],
                {"object_id": source_object.id, "field_key": field_key},
                {
                    "field_name": FIELD_NAMES[field_key],
                    "data_type": "number" if is_measure else "string",
                    "is_primary_key": field_key == "FMATERIALBASEID",
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
                    "field_name": FIELD_NAMES[field_key],
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
            await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.name == SYNC_JOB_NAME))
        ).scalars().first()
        if job is None:
            job = MetaSyncJobModel(name=SYNC_JOB_NAME)
            db.add(job)
        job.source_system_id = system.id
        job.source_object_id = source_object.id
        job.standard_entity_id = standard_entity.id
        job.org_code = ORG_CODE
        job.cron_expr = SYNC_CRON
        job.request_params = REQUEST_PARAMS
        job.variables = []
        job.sync_mode = "full"
        job.status = 0
        job.description = "存货收发存汇总表（GetSysReportData）：核算组织 {{org_code}}、仓库区间 JXCPC~JXCPC"
        await db.flush()
        job_id = job.id

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
        metric.source_entity_id = standard_entity.id
        metric.status = 0
        metric.description = DESCRIPTION
        await db.flush()
        print(f"金蝶连接 id={connection.id}，来源对象 id={source_object.id}，同步任务 id={job_id}")
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    job = await _load_job(job_id)
    if job is not None:
        register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心机箱成品仓指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
