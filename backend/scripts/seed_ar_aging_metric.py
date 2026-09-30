"""初始化营销中心坏账计提指标（来源：金蝶《应收款账龄分析表》）。

计提规则（按账龄区间对「尚未收款金额（本位币）」计提）：
    0-30 天 0%、31-60 天 5%、61-90 天 10%、
    91-180 天 20%、181-365 天 50%、1 年以上 100%

口径说明：
- 来源对象 ``AR_AgingAnalysis``（应收款账龄分析表），按单据显示（``FByBill=true``），
  取「尚未收款金额（本位币）``FBalanceAmt`` + 业务日期 ``FDate`` + 到期日 ``FEndDate``」；
  账龄基准默认到期日，无到期日时退化为业务日期（改口径只改 ``MEASURES``）。
- 明细维度是往来单位（客户）：剔除编码 100-113 的内部客户，与「营销中心应收余额」一致。
- 该报表一次全量约 7MB/组织，按天落批次会迅速撑大 ``meta_sync_run``，因此**不落批次**：
  来源对象下按组织登记 14 个同步任务（只提供组织编码与结算组织内码，不配 Cron），
  计算时由引擎并发实时取数（见 ``app/modules/metric/engine.py`` 的 ``_fetch_live_aging_payloads``）。
- 账龄截止日 = 期末日；当期未到期末取今天（月指标每日重算当月时即为当天账龄）。

用法：
    python scripts/seed_ar_aging_metric.py
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
from app.modules.erp.kingdee.client import KingdeeBillQueryRequest, KingdeeClient  # noqa: E402
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
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SOURCE_OBJECT_CODE = "AR_AgingAnalysis"
SOURCE_OBJECT_NAME = "应收款账龄分析表"
STANDARD_ENTITY_CODE = "ar_aging_analysis"
STANDARD_ENTITY_NAME = "应收款账龄分析表"
METRIC_CODE = "marketing_bad_debt_provision"
METRIC_NAME = "营销中心坏账计提"

# 报表返回列（金蝶 WebAPI《应收款账龄分析表》文档「参数FieldKeys显示列」）
FIELD_KEYS = [
    ("FContactUnitNumber", "往来单位编码", "string"),
    ("FCONTACTUNIT", "往来单位名称", "string"),
    ("FBillNo", "单据编号", "string"),
    ("FDate", "业务日期", "date"),
    ("FEndDate", "到期日", "date"),
    ("FBalanceAmt", "尚未收款金额(本位币)", "number"),
    ("FBalanceAmtFor", "尚未收款金额(原币)", "number"),
    ("FCurrencyName", "币别", "string"),
    ("FMasterCurrencyName", "币别(本位币)", "string"),
    ("FSettleOrgName", "结算组织", "string"),
    ("FSaleOrgName", "销售组织", "string"),
    ("FSaleDeptName", "销售部门", "string"),
    ("FSalerName", "销售员", "string"),
    ("FBillTypeName", "单据类型", "string"),
]
DIMENSION_KEYS = {
    "FContactUnitNumber",
    "FCONTACTUNIT",
    "FBillNo",
    "FDate",
    "FEndDate",
    "FCurrencyName",
    "FMasterCurrencyName",
    "FSettleOrgName",
    "FSaleOrgName",
    "FSaleDeptName",
    "FSalerName",
    "FBillTypeName",
}

# 账龄区间：账龄天数 ≤ max_days 的档位比例（max_days 为 None 表示兜底档）
BUCKETS = [
    {"max_days": 30, "rate": 0.0},
    {"max_days": 60, "rate": 0.05},
    {"max_days": 90, "rate": 0.10},
    {"max_days": 180, "rate": 0.20},
    {"max_days": 365, "rate": 0.50},
    {"max_days": None, "rate": 1.0},
]
AGING_SECTIONS = [
    {"FSection": "0-30", "FDays": 30},
    {"FSection": "31-60", "FDays": 60},
    {"FSection": "61-90", "FDays": 90},
    {"FSection": "91-180", "FDays": 180},
    {"FSection": "181-365", "FDays": 365},
    {"FSection": "365以上", "FDays": 0},
]

OBJ_VARIABLES = [
    {
        "name": "aging_date",
        "value_type": "expression",
        # 账龄截止日 = 期末日；当期未到期末取今天（与引擎 period_end 逻辑一致）
        "value": (
            "min(today, (now.replace(day=1) + timedelta(days=32)).replace(day=1) "
            "- timedelta(days=1)).strftime('%Y-%m-%d')"
        ),
        "description": "账龄截止日（期末日，当期取今天）",
    },
    {
        "name": "settle_org_id",
        "value_type": "string",
        "value": "",
        "description": "结算组织内码（由同步任务按组织覆盖）",
    },
]

# 请求模板：FSettleOrgLst 要的是组织内码，FByDate 是账龄截止日（必填）
REQUEST_PARAMS = {
    "FieldKeys": ",".join(key for key, _name, _type in FIELD_KEYS),
    "SchemeId": "",
    "StartRow": 0,
    "Limit": 2000,
    "IsVerifyBaseDataField": "true",
    "FilterString": [],
    "Model": {
        "FAffiliation": {"FNAME": ""},
        "FOutSettle": "false",
        "FAccountSystem": {"FNumber": ""},
        "FSettleOrgLst": "{{settle_org_id}}",
        "FIsFromFilter": "false",
        "FInSettle": "false",
        "FByDate": "{{aging_date}}",
        "FByBill": "true",
        "FUnAudit": "false",
        "FIncludePayEvaluate_New": "false",
        "FOnlyShowPayEvaluate_New": "false",
        "FShowSumLocal": "false",
        "FShowLocal": "false",
        "FGroupCustomer": "false",
        "FToEndDate": "false",
        "FNoPreReceive": "false",
        "FOnlyShowPreReceive": "false",
        "FCONTACTUNITMUL": "",
        "FMULCONTACT": "false",
        "FEXCLUDEB2CAR": "false",
        "FReSetAllocateExc": "false",
        "FExChangeRateType": {"FNUMBER": "HLTX01_SYS"},
        "FAgingCalStd": "0",
        # 账龄分组设置：报表带该设置时才返回「尚未收款金额（本位币）」
        "FEntAgingGrpSetting": AGING_SECTIONS,
    },
}

MEASURES = {
    "kind": "ar_aging_provision",
    "source_object_code": SOURCE_OBJECT_CODE,
    # 计提口径：按往来单位取净值，客户净额 ≤ 0 的不纳入计提（改为 "bill" 即逐单计提）
    "netting": "customer",
    "amount_field": "FBalanceAmt",
    "customer_code_field": "FContactUnitNumber",
    "customer_name_field": "FCONTACTUNIT",
    "bill_no_field": "FBillNo",
    "date_field": "FEndDate",
    "fallback_date_field": "FDate",
    "detail_is_department": False,
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
    "max_concurrency": 3,
    "buckets": BUCKETS,
}
DIMENSIONS = {"org": True, "dept": True}


async def get_or_create(db, model, **kwargs):
    match_keys = {
        SourceSystemModel: ["code"],
        SourceObjectModel: ["system_id", "code"],
        SourceFieldModel: ["object_id", "field_key"],
        StandardEntityModel: ["code"],
        StandardFieldModel: ["entity_id", "field_code"],
        MetaSyncJobModel: ["name"],
    }.get(model, ["id"])
    conditions = [getattr(model, key) == kwargs[key] for key in match_keys if key in kwargs]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**kwargs)
        db.add(obj)
    else:
        for key, value in kwargs.items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def fetch_org_ids() -> dict[str, str]:
    """取金蝶组织编码 → 组织内码（账龄分析表的结算组织参数要内码）。"""
    client = KingdeeClient.from_ini(INI_PATH)
    _fields, items = await client.bill_query(
        KingdeeBillQueryRequest(form_id="ORG_Organizations", field_keys="FNumber,FOrgID", limit=200)
    )
    return {str(item["FNumber"]): str(item["FOrgID"]) for item in items if item.get("FOrgID")}


async def main() -> None:
    conf = configparser.ConfigParser()
    conf.read(INI_PATH, encoding="utf-8")

    org_ids = await fetch_org_ids()
    missing_orgs = [str(code) for code in range(100, 114) if str(code) not in org_ids]
    if missing_orgs:
        print(f"警告：金蝶未取到以下组织内码，对应同步任务将沿用库里已有值：{missing_orgs}")

    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(KingdeeConnectionModel).where(KingdeeConnectionModel.name == "金蝶默认连接"))
        ).scalars().first()
        if connection is None:
            connection = KingdeeConnectionModel(
                name="金蝶默认连接",
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
            code="kingdee",
            name="金蝶云星空",
            connector_type="kingdee",
            connection_id=connection.id,
            status=0,
        )
        source_object = await get_or_create(
            db,
            SourceObjectModel,
            system_id=system.id,
            code=SOURCE_OBJECT_CODE,
            name=SOURCE_OBJECT_NAME,
            query_type="sys_report",
            request_template=REQUEST_PARAMS,
            variables=OBJ_VARIABLES,
            status=0,
        )
        standard_entity = await get_or_create(
            db,
            StandardEntityModel,
            code=STANDARD_ENTITY_CODE,
            name=STANDARD_ENTITY_NAME,
            table_name="dwd_ar_aging_analysis",
            status=0,
        )

        for field_key, field_name, data_type in FIELD_KEYS:
            source_field = await get_or_create(
                db,
                SourceFieldModel,
                object_id=source_object.id,
                field_key=field_key,
                field_name=field_name,
                data_type=data_type,
                is_primary_key=field_key == "FBillNo",
                is_watermark=False,
                status=0,
            )
            standard_field = await get_or_create(
                db,
                StandardFieldModel,
                entity_id=standard_entity.id,
                field_code=field_key,
                field_name=field_name,
                data_type=data_type,
                is_dimension=field_key in DIMENSION_KEYS,
                is_measure=field_key not in DIMENSION_KEYS,
                status=0,
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

        for org_code in [str(code) for code in range(100, 114)]:
            job = (
                await db.execute(
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"应收款账龄分析表-组织{org_code}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"应收款账龄分析表-组织{org_code}", org_code=org_code)
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.standard_entity_id = standard_entity.id
            # 指标计算时实时取数，这里不配 Cron（留空即不注册定时任务）
            job.cron_expr = ""
            job.request_params = REQUEST_PARAMS
            org_id = org_ids.get(org_code)
            if org_id or job.variables is None:
                job.variables = [
                    {
                        "name": "settle_org_id",
                        "value_type": "string",
                        "value": org_id or "",
                        "description": f"金蝶结算组织内码（组织 {org_code}）",
                    }
                ]
            job.sync_mode = "full"
            job.status = 0
            job.description = "账龄计提指标实时取数用：登记组织与结算组织内码，不参与定时同步"
            await db.flush()

        metric = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code == METRIC_CODE))
        ).scalars().first()
        if metric is None:
            metric = MetricDefModel(code=METRIC_CODE)
            db.add(metric)
        metric.name = METRIC_NAME
        metric.period_type = "month"
        metric.sensitivity = 0
        metric.formula = (
            "SUM(客户净额 × 账龄比例) WHERE 来源=应收款账龄分析表(按单据) AND 客户净额 > 0 "
            "AND 往来单位 NOT IN (100,101,102,103,104,105,106,107,108,109,110,111,112,113)"
        )
        metric.dimensions = DIMENSIONS
        metric.measures = MEASURES
        metric.source_entity_id = standard_entity.id
        metric.status = 0
        metric.description = (
            "营销中心月度报表使用：金蝶《应收款账龄分析表》按单据的「尚未收款金额（本位币）」，"
            "先按往来单位汇总净值（应收与预收相抵），**客户净额为负（含 0）的不纳入计提**，"
            "净额为正的客户再按账龄区间计提：0-30 天 0%、31-60 天 5%、61-90 天 10%、"
            "91-180 天 20%、181-365 天 50%、1 年以上 100%；账龄基准默认到期日（无到期日按业务日期），"
            "剔除编码 100-113 的内部客户，明细维度为往来单位（客户）。"
            "账龄截止日 = 期末日（当期取今天）；月指标，每日重算当月数值，每次计算保留 calc_version 版本。"
        )
        await db.flush()
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")
        print(f"来源对象 id={source_object.id} code={source_object.code}")

    await async_engine.dispose()
    print("应收款账龄计提元数据初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
