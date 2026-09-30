"""初始化营销中心 CRM 订单/报价系列指标（连接 + 元数据 + 同步任务 + 指标定义）。

数据源：CRM《订单未税金额接口文档》《报价单统计接口文档》，域名
``http://crmapi.yonggubox.com``，全部接口 ``GET``、**无需登录/令牌**；
公共参数 ``dateRange`` 按**整月闭区间**渲染（``月初 ~ 月末``）。

口径要点：
- 订单类：内贸/外贸/零售/批量/打样/设计费接口仅统计有效订单 ``status=384``；
  **备货订单**接口不按 ``status=384`` 过滤，仅按日期统计 ``order_stock`` 表；
  各接口 ``data`` 即已算好的未税金额，本系统直接取值、不再二次折算。
- 报价类：报价次数取「全部报价单」（``transformation=0``）的 ``quoteCount``；
  报价成功率 = ``orderCount`` ÷ ``quoteCount`` ×100%；报价毛利率直接取接口
  ``grossProfitRate``（接口已是百分数）。
- 汇总类：接单金额（未税）= 零售/批量/打样/备货订单（未税）+ 设计费收入（未税）当期结果合计
  （``kind = metric_sum``，不单独调接口，计算时先补齐缺结果的组成指标）。**内贸/外贸订单不计入**：
  它们是「该方向全部订单」的总计，与按 ``order_type`` 拆分的零售/批量/打样重复。
- 订单数：``/hs/getOrderCount``（控制器 ``app\\api\\controller\\accounting\\v1\\XcOrder``）
  返回内贸 + 外贸 + 零售三类有效订单（``status=384``）的条数合计，取值路径 ``data.count``；
  客单价 = 接单金额（未税）÷ 订单数（``kind = metric_ratio``，分母为 0 时取 0）。

声明式维护：``SOURCE_OBJECTS`` 一个接口一条（同步任务按接口建，多个指标可共用），
``METRICS`` 一个指标一条，加指标只需在 ``METRICS`` 里加一条。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_marketing_metrics.py
    python scripts/seed_crm_marketing_metrics.py --base-url http://crmapi.yonggubox.com
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

CONNECTION_NAME = "CRM 默认连接"
SOURCE_SYSTEM_CODE = "crm"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

# 整月日期范围模板：{{ }} 由元数据同步任务渲染，now = 取数时点（回补时为该期间 1 日）
MONTH_DATE_RANGE: dict = {
    "dateRange": [
        "{{ now.replace(day=1).strftime('%Y-%m-%d') }}",
        "{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d') }}",
    ]
}

# 取数规则：由指标计算引擎解释（kind=api_scalar_amount 直接取响应 data 数值）
BASE_MEASURES = {
    "kind": "api_scalar_amount",
    "data_field": "data",
}
DIMENSIONS = {"org": False, "dept": False}

# 一个接口一条：params 是 dateRange 之外的固定请求参数（同步任务按接口建，多个指标共用）
SOURCE_OBJECTS = [
    {"path": "/hs/order/getDtAmount", "name": "营销中心内贸订单（未税）", "params": {}},
    {"path": "/hs/order/getFtAmount", "name": "营销中心外贸订单（未税）", "params": {}},
    {"path": "/hs/order/getRetailAmount", "name": "营销中心零售订单（未税）", "params": {}},
    {"path": "/hs/order/getBatchAmount", "name": "营销中心批量订单（未税）", "params": {}},
    {"path": "/hs/order/getSampleAmount", "name": "营销中心打样订单（未税）", "params": {}},
    {"path": "/hs/order/getStockUpAmount", "name": "营销中心备货订单（未税）", "params": {}},
    {"path": "/hs/order/getDesignAmount", "name": "营销中心设计费收入（未税）", "params": {}},
    # 报价单统计：transformation=0（全部报价单），成功率与次数共用同一份取数
    {"path": "/hs/quote/getQuoteStatistics", "name": "报价单统计", "params": {"transformation": 0}},
    {"path": "/hs/quote/getQuoteProfitRate", "name": "报价单毛利率", "params": {}},
    # 订单数量统计（XcOrder/getOrderCount）：客单价的分母
    {"path": "/hs/getOrderCount", "name": "营销中心订单数", "params": {}},
]

# 一个指标一条：measures 追加到 BASE_MEASURES，path 必须出现在 SOURCE_OBJECTS 中
METRICS = [
    {
        "code": "marketing_domestic_order_untaxed",
        "name": "营销中心内贸订单（未税）",
        "path": "/hs/order/getDtAmount",
        "rule": "内贸订单未税金额 = SUM(receivable - taxes)，订单有效状态 status=384，按订单日期 createtime。",
    },
    {
        "code": "marketing_export_order_untaxed",
        "name": "营销中心外贸订单（未税）",
        "path": "/hs/order/getFtAmount",
        "rule": "外贸订单未税金额 = SUM(receivable_CNY)，订单有效状态 status=384，按订单日期 createtime。",
    },
    {
        "code": "marketing_retail_order_untaxed",
        "name": "营销中心零售订单（未税）",
        "path": "/hs/order/getRetailAmount",
        "rule": "status=384 的外贸订单中 order_type=3 的 SUM(receivable_CNY) + retail_order 表 status=384 的 "
        "SUM(receivable - taxes)，按订单日期 createtime。",
    },
    {
        "code": "marketing_batch_order_untaxed",
        "name": "营销中心批量订单（未税）",
        "path": "/hs/order/getBatchAmount",
        "rule": "内贸订单 order_type=1 的 SUM(receivable - taxes) + 外贸订单 order_type=1 的 SUM(receivable_CNY)，"
        "status=384，按订单日期 createtime。",
    },
    {
        "code": "marketing_sample_order_untaxed",
        "name": "营销中心打样订单（未税）",
        "path": "/hs/order/getSampleAmount",
        "rule": "内贸订单 order_type=2 的 SUM(receivable - taxes) + 外贸订单 order_type=2 的 SUM(receivable_CNY)，"
        "status=384，按订单日期 createtime。",
    },
    {
        "code": "marketing_stockup_order_untaxed",
        "name": "营销中心备货订单（未税）",
        "path": "/hs/order/getStockUpAmount",
        "rule": "order_stock 表 SUM(qty * price)，**不按 status=384 过滤**，仅按日期范围统计。",
    },
    {
        "code": "marketing_design_income_untaxed",
        "name": "营销中心设计费收入（未税）",
        "path": "/hs/order/getDesignAmount",
        "rule": "内贸订单 SUM(design_remove_taxes_freight) + 外贸订单 SUM(design_cost)，status=384，按订单日期 createtime。",
    },
    {
        "code": "marketing_quote_count",
        "name": "营销中心报价次数",
        "path": "/hs/quote/getQuoteStatistics",
        "rule": "当期报价单数量 = Σ报价单 = quoteCount（transformation=0 全部报价单），按报价日期 dateRange。",
        # unit 是给开放接口/文档用的展示单位（默认元），非金额指标必须显式声明
        "measures": {"data_field": "data.quoteCount", "unit": "次"},
    },
    {
        "code": "marketing_quote_success_rate",
        "name": "营销中心报价成功率",
        "path": "/hs/quote/getQuoteStatistics",
        "rule": "报价转接单次数 ÷ 报价次数 ×100% = orderCount ÷ quoteCount（同一份 transformation=0 取数）。",
        "measures": {
            "data_field": "data.quoteCount",
            "numerator_field": "data.orderCount",
            "denominator_field": "data.quoteCount",
            "ratio_scale": 100,
            "unit": "%",
        },
    },
    {
        "code": "marketing_quote_profit_rate",
        "name": "营销中心报价毛利率",
        "path": "/hs/quote/getQuoteProfitRate",
        "rule": "报价预估毛利 ÷ 报价未税金额 ×100%，接口直接返回该比率（grossProfitRate，百分数）。",
        "measures": {"data_field": "data.grossProfitRate", "unit": "%"},
    },
    {
        # 汇总指标：不取数，直接合计下面 5 个订单类指标当期结果
        # 注意：内贸/外贸是「该方向全部订单」的总计，零售/批量/打样是按 order_type 的明细切分，
        # 属于内贸+外贸的子集，两者同时计入会重复约 86%~94%，因此只取明细侧（零售/批量/打样）。
        "code": "marketing_order_intake_untaxed",
        "name": "营销中心接单金额（未税）",
        "path": None,
        "rule": "接单金额（未税）= 零售订单 + 批量订单 + 打样订单 + 备货订单 + 设计费收入（均未税）；"
        "内贸/外贸订单是全部订单的总计，已由前三项按 order_type 拆分覆盖，不重复计入。",
        "measures": {
            "kind": "metric_sum",
            "component_metric_codes": [
                "marketing_retail_order_untaxed",
                "marketing_batch_order_untaxed",
                "marketing_sample_order_untaxed",
                "marketing_stockup_order_untaxed",
                "marketing_design_income_untaxed",
            ],
        },
    },
    {
        # 订单数量：CRM /hs/getOrderCount 返回的 data.count（内贸 + 外贸 + 零售有效订单条数合计）
        "code": "marketing_order_count",
        "name": "营销中心订单数",
        "path": "/hs/getOrderCount",
        "rule": "订单数 = 内贸 + 外贸 + 零售三类有效订单（status=384）的条数合计"
        "（三表 COUNT(*) 之和，接口 data.count，无小数）；按订单创建时间 createtime 落在期间内统计，"
        "不限制 has_finish/chuhuo/order_type/qty，也不看金额。",
        "source_text": "数据来源：CRM《HASH 接口文档》 app\\api\\controller\\accounting\\v1\\XcOrder "
        "/hs/getOrderCount（GET、无需鉴权，dateRange 为整月闭区间）；",
        # 非金额指标：显式声明单位，避免开放接口/文档按名称兜底写成「元」
        "measures": {"data_field": "data.count", "unit": "单"},
    },
    {
        # 比率指标：不取数，值 = 分子指标当期值 ÷ 分母指标当期值 × ratio_scale
        "code": "marketing_order_price",
        "name": "营销中心客单价",
        "path": None,
        "rule": "**客单价** = 接单金额（未税）÷ 订单数（元/单，分母为 0 时取 0）："
        "分子取「营销中心接单金额（未税）」（= 零售/批量/打样/备货订单（未税）+ 设计费收入（未税）），"
        "分母取「营销中心订单数」（= 内贸 + 外贸 + 零售三类有效订单 status=384 的条数合计），"
        "两者同为当月、同口径。",
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": ["marketing_order_intake_untaxed"],
            "denominator_metric_codes": ["marketing_order_count"],
            "ratio_scale": 1,
            "unit": "元/单",
        },
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="初始化营销中心 CRM 订单未税金额指标")
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
                "description": "CRM 订单未税金额接口（无需鉴权）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        # 先建接口（来源对象 + 同步任务），多个指标可共用同一接口的取数批次
        for spec in SOURCE_OBJECTS:
            path = spec["path"]
            request_template = {**MONTH_DATE_RANGE, **spec.get("params", {})}
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
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM订单指标-{spec['name']}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM订单指标-{spec['name']}")
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.org_code = None
            job.cron_expr = args.cron
            job.request_params = request_template
            job.sync_mode = "full"
            job.status = 0
            job.description = f"CRM 接口 {path}，按日期取整月（闭区间）"
            await db.flush()
            job_ids.append(job.id)

        for spec in METRICS:
            code = spec["code"]
            name = spec["name"]
            path = spec["path"]
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == code))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=code)
                db.add(metric)
            metric.name = name
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.dimensions = DIMENSIONS
            measures = {**BASE_MEASURES, **spec.get("measures", {})}
            if path:
                measures["source_object_code"] = path
                metric.formula = f"CRM {path} 返回的指标值（dateRange=整月）"
                source_text = spec.get("source_text") or (
                    f"数据来源：CRM《订单未税金额接口文档》《报价单统计接口文档》 {path}；"
                )
            else:
                # 汇总/比率指标不取数：去掉取数专用配置，只保留组成指标清单
                measures.pop("data_field", None)
                measures.pop("source_object_code", None)
                if measures.get("kind") == "metric_ratio":
                    # 比率指标：分子 ÷ 分母 × ratio_scale（如客单价 = 接单金额 ÷ 订单数）
                    numerator_codes = [str(code) for code in measures.get("numerator_metric_codes") or []]
                    denominator_codes = [str(code) for code in measures.get("denominator_metric_codes") or []]
                    ratio_scale = float(measures.get("ratio_scale") or 1)
                    suffix = f" × {ratio_scale:g}" if ratio_scale != 1 else ""
                    metric.formula = (
                        f"({' + '.join(numerator_codes)}) ÷ ({' + '.join(denominator_codes)}){suffix}"
                    )
                    component_codes = [*numerator_codes, *denominator_codes]
                    source_text = (
                        f"数据来源：本系统内 {len(component_codes)} 个营销中心 CRM 订单指标当期结果（相除）；"
                    )
                else:
                    component_codes = [str(code) for code in measures.get("component_metric_codes") or []]
                    metric.formula = "SUM(" + " + ".join(component_codes) + ")"
                    source_text = (
                        f"数据来源：本系统内下列 {len(component_codes)} 个营销中心 CRM 订单指标的结果合计；"
                    )
            metric.measures = measures
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{spec['rule']} {source_text}"
                "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

        print(f"CRM 连接 id={connection.id}，来源系统 id={system.id}，同步任务 {job_ids}")

    for job_id in job_ids:
        job = await _load_job(job_id)
        if job is not None:
            register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心 CRM 订单未税金额指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
