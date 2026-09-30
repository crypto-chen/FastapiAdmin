"""初始化「营销中心当期备货生产入库指标」（金蝶生产入库单 → 生产订单 Y订单金额）。

口径（由 ``metric_def.measures`` 声明，改口径只改这里）：

1. 取**本期生产入库单**（金蝶 ``PRD_INSTOCK``，``ExecuteBillQuery`` 单据查询）：
   已审核（``FDocumentStatus='C'``）、``FDate`` 落在本期（月起 ~ 月末闭区间）；
2. 只要**需求单据以 ``BH`` 开头**的分录（备货订单，字段 ``FReqBillNo``）；
3. 单据里的生产订单号（``FMoBillNo``）关联到生产订单 ``PRD_MO`` 单据头，
   取 ``F_UIVG_Decimal_83g``（Y订单金额）、``FMaterialId.FNumber``（物料）与 ``FQty``（生产数量）；
4. 结算口径分两类：

   - **生产订单物料含 ``C.``**（半成品订单，常对应多个成品分录/多次入库）：
     同一张生产订单当月**只计一次**整单金额；
   - **其他订单（如 ``BCP`` 成品、分多次入库）**：按**单价**结转，
     单价 = 单据头金额 ÷ 生产数量，金额 = Σ(该订单本期入库数量 × 单价)；
     生产数量为 0/缺失时退化为整单金额计一次。

结果同时给出按「需求单据（备货订单号）」拆分的明细，便于穿透核对。

同步任务每天 02:00 取本月生产入库单（早于指标调度的 02:30）；月指标每日重算当月，
次月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_stockup_instock_metric.py

说明：该口径原先挂在指标「营销中心备货订单库存」（code=``marketing_stockup_order_instock``）上，
现迁移到本指标；旧指标不再由本脚本改写——它的新口径（海柔库存 + 机箱成品仓）
已改由 `scripts/seed_marketing_stockup_inventory_metric.py` 维护，历史结果保留。
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
SOURCE_OBJECT_CODE = "PRD_INSTOCK"
SOURCE_OBJECT_NAME = "生产入库单"
STANDARD_ENTITY_CODE = "production_instock"
STANDARD_ENTITY_NAME = "生产入库单"
STANDARD_TABLE_NAME = "dwd_production_instock"
METRIC_CODE = "marketing_stockup_prod_instock"
METRIC_NAME = "营销中心当期备货生产入库指标"
# 旧指标（口径已迁出，改由 seed_marketing_stockup_inventory_metric.py 维护）：本脚本不再改写
LEGACY_METRIC_CODES = ["marketing_stockup_order_instock"]
SYNC_JOB_NAME = "生产入库单-营销中心当期备货生产入库"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

# 生产入库单分录字段（FieldKeys 的顺序即接口返回值的顺序）
SOURCE_FIELDS = [
    ("FBillNo", "单据编号", True),
    ("FDate", "入库日期", False),
    ("FDocumentStatus", "单据状态", False),
    ("FPrdOrgId.FNumber", "生产组织编码", False),
    ("FMoBillNo", "生产订单号", False),
    ("FReqBillNo", "需求单据", False),
    ("FMaterialId.FNumber", "物料编码", False),
    ("FRealQty", "实收数量", False),
]
MEASURE_FIELD_KEYS = {"FRealQty"}

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
    "FieldKeys": ",".join(field_key for field_key, _name, _pk in SOURCE_FIELDS),
    "FilterString": "FDocumentStatus='C' and FDate>='{{month_start}}' and FDate<='{{month_end}}'",
    "OrderString": "FBillNo",
    "TopRowCount": 0,
}

# 取数规则：由指标计算引擎解释（kind=production_instock_amount）
MEASURES = {
    "kind": "production_instock_amount",
    "source_object_code": SOURCE_OBJECT_CODE,
    "demand_field": "FReqBillNo",
    "demand_prefix": "BH",
    "order_field": "FMoBillNo",
    "order_form_id": "PRD_MO",
    "order_number_field": "FBillNo",
    "order_amount_field": "F_UIVG_Decimal_83g",
    "order_material_field": "FMaterialId.FNumber",
    "order_qty_field": "FQty",
    "inbound_qty_field": "FRealQty",
    "order_status_filter": "FDocumentStatus='C'",
    # 生产订单物料含 C.（半成品订单）时，同一生产订单当月只计一次整单金额
    "dedupe_material_keyword": "C.",
    # 明细维度是需求单据（备货订单号），不是部门
    "detail_is_department": False,
}
DIMENSIONS = {"org": False, "dept": False, "demand": True}

FORMULA = (
    "SUM(生产订单.F_UIVG_Decimal_83g) WHERE 生产入库单.需求单据 LIKE 'BH%' "
    "AND 单据状态=已审核 AND 入库日期∈期间；"
    "生产订单物料含 C. → 按生产订单号去重只计一次整单金额；"
    "其余订单 → Σ(生产入库实收数量 × 生产订单金额 ÷ 生产数量)"
)
DESCRIPTION = (
    "营销中心当期备货生产入库指标：取本期已审核生产入库单（金蝶 PRD_INSTOCK）中需求单据（FReqBillNo）"
    "以 BH 开头的分录，按生产订单号（FMoBillNo）关联生产订单（PRD_MO）：生产订单物料含 C. 的"
    "（半成品订单，常对应多个成品分录/多次入库）当月只计一次整单 Y订单金额（F_UIVG_Decimal_83g）；"
    "其余订单按单价结转——单价 = Y订单金额 ÷ 生产数量（FQty），金额 = Σ(本期入库数量 FRealQty × 单价)。"
    "明细按备货订单号（需求单据）拆分。"
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
                "query_type": "bill_query",
                "request_template": REQUEST_PARAMS,
                "variables": OBJECT_VARIABLES,
                "status": 0,
            },
        )
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

        for field_key, field_name, is_pk in SOURCE_FIELDS:
            is_measure = field_key in MEASURE_FIELD_KEYS
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
        job.description = "生产入库单（ExecuteBillQuery）：已审核、按入库日期取本期单据，不分组织"
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
        print(f"金蝶连接 id={connection.id}，来源系统 id={system.id}，来源对象 id={source_object.id}，同步任务 id={job_id}")
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

        # 旧指标口径已迁出，且已有新的库存口径（海柔库存 + 机箱成品仓），这里只提示不动它，
        # 避免重跑本脚本把「营销中心备货订单库存」的取数配置清掉。
        for legacy_code in LEGACY_METRIC_CODES:
            print(
                f"提示：{legacy_code} 的口径已迁出本脚本，"
                "新口径见 scripts/seed_marketing_stockup_inventory_metric.py"
            )

    job = await _load_job(job_id)
    if job is not None:
        register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心备货订单库存指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
