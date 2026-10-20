"""初始化营销中心「订单下推周期」系列指标（连接 + 元数据 + 同步任务 + 指标定义）。

数据源：CRM《订单下推周期接口文档》，域名 ``http://crmapi.yonggubox.com``，
全部接口 ``GET``、**无需登录/令牌**，统一返回
``{"code": 1, "msg": "", "time": ..., "data": 数值}``。

过滤口径（所有接口通用）：仅统计 ``erp_push_status = 1`` 且 ``status = 384``
（订单有效状态）的订单；无匹配数据返回 ``0``。

金额口径 vs 周期口径（**两套口径混在一个接口族里，取值前必须先看是哪种**）：

- ``/hs/push/getPush``（「本月接单本月下推 / 前期接单本月下推」）取值为
  **内贸 + 外贸未税金额合计**，入参为 ``dateRange``（ERP 下推时间整月）+ ``type``：
  ``type=1`` = 本月创建本月下推，``type=2`` = 非本月创建但本月下推；
  金额 = 内贸 ``SUM(receivable - taxes)`` + 外贸 ``SUM(receivable_CNY)``（元，保留 2 位小数）；
- 其余 9 个 ``*PushPeriod`` 接口取值为**平均下推周期（天）**：
  平均「下单时间 ``createtime`` → ERP 下推时间 ``erp_push_date``」的耗时。

13 个指标 = 11 个接口（``/hs/push/getPush`` 用 ``type=1`` / ``type=2`` 拆成 2 个指标）
  + 1 个汇总指标（**下推金额合计 = 上面两条相加**，不单独调接口）
  + 1 个比率指标（下推率，不单独调接口）：

======================  ============================================  ==================================
指标                    接口                                          取值口径（服务端实测）
======================  ============================================  ==================================
本月接单本月下推          ``/hs/push/getPush?type=1``                     下推月 = 本月 且 接单月 = 本月
前期接单本月下推          ``/hs/push/getPush?type=2``                     下推月 = 本月 且 接单时间 < 本月 1 日
下推金额（未税）          ——（``kind=metric_sum``，合计上面两条）          下推月 = 本月（不区分接单月）
下推周期（天）            ``/hs/push/getPushPeriod``                    内贸 + 外贸合并
批量下推周期              ``/hs/push/getBatchPushPeriod``               ``order_type=1``
打样下推周期              ``/hs/push/getSamplePushPeriod``              ``order_type=2``
内贸下推周期              ``/hs/push/getDtPushPeriod``                  内贸订单
外贸下推周期              ``/hs/push/getFtPushPeriod``                  外贸订单
批量内贸下推周期          ``/hs/push/getBatchDtPushPeriod``             内贸 + ``order_type=1``
批量外贸下推周期          ``/hs/push/getBatchFtPushPeriod``             外贸 + ``order_type=1``
打样内贸下推周期          ``/hs/push/getSampleDtPushPeriod``            内贸 + ``order_type=2``
打样外贸下推周期          ``/hs/push/getSampleFtPushPeriod``            外贸 + ``order_type=2``
======================  ============================================  ==================================

两条金额指标的取数范围（模板按期间渲染，``now`` = 取数时点，回补时为该期间 1 日）：

- 本月接单本月下推：``dateRange`` = 本月 1 日 00:00:00 ~ 本月末 23:59:59，``type=1``；
- 前期接单本月下推：``dateRange`` = 本月 1 日 00:00:00 ~ 本月末 23:59:59，``type=2``。

实测校验（2026-09，2026-10-20）：``type=1`` = 7469553.97、``type=2`` = 1806596.18，
两者相加 = 9276150.15 = **下推金额（未税）合计**；
历史月份同样可算（2026-08 → 6492547.07 / 1528911.26），
**这两条和其余 9 条一样支持按月回补，不再是当月快照**。
上游可回补的最早期间是 **2025-08**（2025-07 及更早各接口返回 0），
回补即按期间逐个调用 ``execute_metric_calc(metric_id, period_value)``（同步任务会自动按期间取数）。

与「指标说明表」的差异（以接口实际行为为准，勿按说明表改）：说明表把
「本月接单本月下推 / 前期接单本月下推」写成 ``Σ下推单``（单数），上游实际返回的是
**下推未税金额（元）**，本脚本按金额入库（既不是单数，也不是天数；未税口径由上游保证，
本系统直接取值、不做二次折算）。

接口路径即来源对象 ``code``；两条金额指标打在同一接口上，靠 ``code`` 里的
``?type=1`` / ``?type=2`` 区分，``dateRange`` 由请求模板传（整月，含 00:00:00 / 23:59:59）。
声明式维护：``SOURCE_OBJECTS`` 一个接口一条，``METRICS`` 一个指标一条。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_push_metrics.py
    python scripts/seed_crm_push_metrics.py --base-url http://crmapi.yonggubox.com
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
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

# 与 seed_crm_marketing_metrics.py / seed_crm_shipment_metrics.py 共用同一个 CRM 连接与来源系统
CONNECTION_NAME = "CRM 默认连接"
SOURCE_SYSTEM_CODE = "crm"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

# 日期范围模板：{{ }} 由元数据同步任务渲染，now = 取数时点（回补时为该期间 1 日）
MONTH_START = "{{ now.replace(day=1).strftime('%Y-%m-%d') }}"
MONTH_END = (
    "{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d') }}"
)
# 整月闭区间（其余 9 个 *PushPeriod 接口用）
MONTH_DATE_RANGE: dict = {"dateRange": [MONTH_START, MONTH_END]}

# 两条金额指标：dateRange 固定为「下推时间」整月，type=1 / type=2 由来源对象 code 区分。
# 时间部分按接口文档写成 00:00:00 ~ 23:59:59，避免上游把日期解析成 00:00:00 时丢掉月末当天。
PUSH_AMOUNT_PARAMS: dict = {
    "dateRange": [
        "{{ now.replace(day=1).strftime('%Y-%m-%d') }} 00:00:00",
        "{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d') }} 23:59:59",
    ]
}

# 上一版来源对象 code（?scope=...）原地迁移到新版（?type=...），保留对象、同步任务和历史批次。
LEGACY_SCOPE_CODE_MAP = {
    "/hs/push/getPush?scope=same_month": "/hs/push/getPush?type=1",
    "/hs/push/getPush?scope=prior_month": "/hs/push/getPush?type=2",
}

BASE_MEASURES = {"kind": "api_scalar_amount", "data_field": "data"}
DIMENSIONS = {"org": False, "dept": False}

# 一个接口一条。``date_range=False`` 表示 dateRange 已写在 params 里（仅 getPush 两条金额指标）。
SOURCE_OBJECTS = [
    {
        "path": "/hs/push/getPush?type=1",
        "name": "营销中心本月接单本月下推（未税）",
        "params": PUSH_AMOUNT_PARAMS,
        "date_range": False,
    },
    {
        "path": "/hs/push/getPush?type=2",
        "name": "营销中心前期接单本月下推（未税）",
        "params": PUSH_AMOUNT_PARAMS,
        "date_range": False,
    },
    {"path": "/hs/push/getPushPeriod", "name": "营销中心下推周期（天）", "params": {}},
    {"path": "/hs/push/getBatchPushPeriod", "name": "营销中心批量下推周期", "params": {}},
    {"path": "/hs/push/getSamplePushPeriod", "name": "营销中心打样下推周期", "params": {}},
    {"path": "/hs/push/getDtPushPeriod", "name": "营销中心内贸下推周期", "params": {}},
    {"path": "/hs/push/getFtPushPeriod", "name": "营销中心外贸下推周期", "params": {}},
    {"path": "/hs/push/getBatchDtPushPeriod", "name": "营销中心批量内贸下推周期", "params": {}},
    {"path": "/hs/push/getBatchFtPushPeriod", "name": "营销中心批量外贸下推周期", "params": {}},
    {"path": "/hs/push/getSampleDtPushPeriod", "name": "营销中心打样内贸下推周期", "params": {}},
    {"path": "/hs/push/getSampleFtPushPeriod", "name": "营销中心打样外贸下推周期", "params": {}},
]

# 口径结尾：金额族（getPush 两条）与周期族（其余 9 条）分开写，避免张冠李戴
COMMON_FILTER = "仅统计 erp_push_status=1 且 status=384（订单有效状态）的订单；"
AMOUNT_RULE = (
    COMMON_FILTER
    + "下推金额（未税）= 内贸 SUM(receivable - taxes) + 外贸 SUM(receivable_CNY)（元，保留 2 位小数）。"
)
PERIOD_RULE = COMMON_FILTER + "下推周期 = Σ(erp_push_date - createtime) ÷ 下推单数（天，保留 2 位小数）。"

# 一个指标一条：path 必须出现在 SOURCE_OBJECTS 中
METRICS = [
    {
        "code": "marketing_order_push_same_month",
        "name": "营销中心本月接单本月下推（未税）",
        "path": "/hs/push/getPush?type=1",
        "amount": True,
        "rule": "当月接单且当月下推（接单月 = 下推月）订单的**下推金额（未税，元）**，"
        "即 dateRange = 本月（下推时间）且 type=1。",
    },
    {
        "code": "marketing_order_push_prior_month",
        "name": "营销中心前期接单本月下推（未税）",
        "path": "/hs/push/getPush?type=2",
        "amount": True,
        "rule": "前期接单（接单时间早于本月 1 日）但本月下推（接单月 < 下推月）订单的"
        "**下推金额（未税，元）**，即 dateRange = 本月（下推时间）且 type=2。",
    },
    {
        # 汇总指标：不取数，直接合计上面两条金额指标的当期结果
        "code": "marketing_order_push_untaxed",
        "name": "营销中心下推金额（未税）",
        "path": None,
        "amount": True,
        "rule": "**下推金额（未税）合计** = 本月接单本月下推（未税）+ 前期接单本月下推（未税），"
        "即 type=1 + type=2，覆盖「ERP 下推时间落在本月」的全部订单（不区分接单月份）。",
        "measures": {
            "kind": "metric_sum",
            "component_metric_codes": [
                "marketing_order_push_same_month",
                "marketing_order_push_prior_month",
            ],
        },
    },
    {
        # 比率指标：不取数，值 = 分子指标当期值 ÷ 分母指标当期值 × ratio_scale
        "code": "marketing_order_push_rate",
        "name": "营销中心下推率",
        "path": None,
        "rule": "**下推率** = 下推金额（未税）÷ 接单金额（未税）（×100 输出百分数，分母为 0 时取 0）；"
        "分子取「营销中心下推金额（未税）」（= 本月接单本月下推 + 前期接单本月下推），"
        "分母取「营销中心接单金额（未税）」，两者同为当月、同口径（未税）。",
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": ["marketing_order_push_untaxed"],
            "denominator_metric_codes": ["marketing_order_intake_untaxed"],
            "ratio_scale": 100,
            "unit": "%",
        },
    },
    {
        "code": "marketing_push_period",
        "name": "营销中心下推周期（天）",
        "path": "/hs/push/getPushPeriod",
        "rule": "接单到下推的平均天数（内贸 + 外贸合并），按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_batch_push_period",
        "name": "营销中心批量下推周期",
        "path": "/hs/push/getBatchPushPeriod",
        "rule": "批量订单（order_type=1）平均下推周期，内贸 + 外贸合并，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_sample_push_period",
        "name": "营销中心打样下推周期",
        "path": "/hs/push/getSamplePushPeriod",
        "rule": "打样订单（order_type=2）平均下推周期，内贸 + 外贸合并，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_domestic_push_period",
        "name": "营销中心内贸下推周期",
        "path": "/hs/push/getDtPushPeriod",
        "rule": "内贸订单（domestic_trade_order）平均下推周期，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_export_push_period",
        "name": "营销中心外贸下推周期",
        "path": "/hs/push/getFtPushPeriod",
        "rule": "外贸订单（foreign_trade_order）平均下推周期，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_batch_domestic_push_period",
        "name": "营销中心批量内贸下推周期",
        "path": "/hs/push/getBatchDtPushPeriod",
        "rule": "批量 + 内贸（内贸订单 order_type=1）平均下推周期，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_batch_export_push_period",
        "name": "营销中心批量外贸下推周期",
        "path": "/hs/push/getBatchFtPushPeriod",
        "rule": "批量 + 外贸（外贸订单 order_type=1）平均下推周期，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_sample_domestic_push_period",
        "name": "营销中心打样内贸下推周期",
        "path": "/hs/push/getSampleDtPushPeriod",
        "rule": "打样 + 内贸（内贸订单 order_type=2）平均下推周期，按 ERP 下推时间 dateRange。",
    },
    {
        "code": "marketing_sample_export_push_period",
        "name": "营销中心打样外贸下推周期",
        "path": "/hs/push/getSampleFtPushPeriod",
        "rule": "打样 + 外贸（外贸订单 order_type=2）平均下推周期，按 ERP 下推时间 dateRange。",
    },
]


async def get_or_create(db, model, match: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == value for key, value in match.items()]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**(defaults or {}), **match})
        db.add(obj)
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    await db.flush()
    return obj


def build_request_template(spec: dict) -> dict:
    """按接口是否支持 dateRange 组装请求模板（getPush 两条的 dateRange 已写在 params 里）。"""
    params = dict(spec.get("params") or {})
    if spec.get("date_range", True):
        return {**MONTH_DATE_RANGE, **params}
    return params


async def main() -> None:
    parser = argparse.ArgumentParser(description="初始化营销中心 CRM 订单下推周期指标")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="CRM 接口域名")
    parser.add_argument("--connection-name", default=CONNECTION_NAME, help="连接名称")
    parser.add_argument("--cron", default=SYNC_CRON, help="同步 Cron（6 段，默认每天 02:00）")
    args = parser.parse_args()

    job_ids: list[int] = []
    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(CrmConnectionModel).where(CrmConnectionModel.name == args.connection_name))
        ).scalars().first()
        if connection is None:
            connection = CrmConnectionModel(name=args.connection_name, base_url=args.base_url, status=0)
            db.add(connection)
            await db.flush()
        else:
            connection.base_url = args.base_url
            connection.status = 0

        system = await get_or_create(
            db,
            SourceSystemModel,
            {"code": SOURCE_SYSTEM_CODE},
            {
                "name": "CRM",
                "connector_type": "crm",
                "connection_id": connection.id,
                "status": 0,
                "description": "CRM 订单/下推/出货/报价接口（无需鉴权）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        # 兼容上一版来源对象 code（?scope=...）：原地改名成 ?type=...，
        # 保留来源对象 id、同步任务和历史同步批次，避免改口径时丢历史。
        for old_code, new_code in LEGACY_SCOPE_CODE_MAP.items():
            old_object = (
                await db.execute(
                    select(SourceObjectModel).where(
                        SourceObjectModel.system_id == system.id,
                        SourceObjectModel.code == old_code,
                    )
                )
            ).scalars().first()
            if old_object is None:
                continue
            conflict = (
                await db.execute(
                    select(SourceObjectModel).where(
                        SourceObjectModel.system_id == system.id,
                        SourceObjectModel.code == new_code,
                    )
                )
            ).scalars().first()
            if conflict is not None and conflict.id != old_object.id:
                print(f"来源对象已存在 {new_code}，跳过 {old_code} 改名")
                continue
            print(f"来源对象 code 迁移: {old_code} -> {new_code}")
            old_object.code = new_code
            await db.flush()

        # 先建接口（来源对象 + 同步任务）
        for spec in SOURCE_OBJECTS:
            path = spec["path"]
            request_template = build_request_template(spec)
            source_object = await get_or_create(
                db,
                SourceObjectModel,
                {"system_id": system.id, "code": path},
                {
                    "name": spec["name"],
                    "query_type": "api",
                    "request_template": request_template,
                    "status": 0,
                },
            )
            source_object.request_template = request_template

            job = (
                await db.execute(
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM下推指标-{spec['name']}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM下推指标-{spec['name']}")
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.org_code = None
            job.cron_expr = args.cron
            job.request_params = request_template
            job.sync_mode = "full"
            job.status = 0
            if spec.get("date_range", True):
                job.description = f"CRM 接口 {path}，按 dateRange 取整月（闭区间）"
            else:
                job.description = (
                    f"CRM 接口 {path}（金额指标：dateRange = 本月下推时间，type 见来源对象 code；"
                    "按期间渲染，可回补历史月份）"
                )
            await db.flush()
            job_ids.append(job.id)

        for spec in METRICS:
            code = spec["code"]
            path = spec["path"]
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == code))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=code)
                db.add(metric)
            metric.name = spec["name"]
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.dimensions = DIMENSIONS
            is_amount = bool(spec.get("amount"))
            unit_text = "下推金额（未税，元）" if is_amount else "平均下推周期（天）"
            if path:
                rule_text = AMOUNT_RULE if is_amount else PERIOD_RULE
                metric.measures = {**BASE_MEASURES, "source_object_code": path}
                metric.formula = f"CRM {path} 返回的{unit_text}"
                source_text = f"数据来源：CRM《订单下推周期接口文档》 {path}（GET、无需鉴权）。"
            else:
                # 汇总/比率指标不取数：去掉取数专用配置，只保留组成指标清单
                rule_text = ""  # 口径已写在 spec['rule'] 里，不再重复单接口口径
                measures = {**BASE_MEASURES, **spec.get("measures", {})}
                measures.pop("data_field", None)
                measures.pop("source_object_code", None)
                metric.measures = measures
                if measures.get("kind") == "metric_ratio":
                    numerator = [str(code) for code in measures.get("numerator_metric_codes") or []]
                    denominator = [str(code) for code in measures.get("denominator_metric_codes") or []]
                    ratio_scale = float(measures.get("ratio_scale") or 1)
                    suffix = f" × {ratio_scale:g}" if ratio_scale != 1 else ""
                    metric.formula = f"({' + '.join(numerator)}) ÷ ({' + '.join(denominator)}){suffix}"
                    component_codes = [*numerator, *denominator]
                    source_text = f"数据来源：本系统内 {len(component_codes)} 个营销中心 CRM 指标当期结果（相除）；"
                else:
                    component_codes = [str(code) for code in measures.get("component_metric_codes") or []]
                    metric.formula = "SUM(" + " + ".join(component_codes) + ")"
                    source_text = f"数据来源：本系统内 {len(component_codes)} 个营销中心 CRM 下推指标当期结果合计；"
            metric.source_entity_id = None
            metric.status = 0
            metric.description = " ".join(
                part
                for part in (
                    spec["rule"],
                    rule_text,
                    source_text,
                    "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。",
                )
                if part
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

        print(f"CRM 连接 id={connection.id}，来源系统 id={system.id}，同步任务 {job_ids}")

    for job_id in job_ids:
        job = await _load_job(job_id)
        if job is not None:
            register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心 CRM 订单下推周期指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
