"""初始化营销中心「KPI」四个指标（连接 + 元数据 + 同步任务 + 指标定义）。

数据源：CRM《KPI 接口文档》，域名 ``http://crmapi.yonggubox.com``，全部接口 ``GET``、
**无需登录/令牌**，统一返回 ``{"code": 1, "msg": "", "time": ..., "data": 数值}``。

四个对外指标（本脚本另建 2 个取数用的辅助指标，共 6 条 ``metric_def``）：

======================  =====================================  ==========================================
指标                    接口                                   取值口径
======================  =====================================  ==========================================
订单履约率               ``/hs/KPI/getOrderFulfillmentRate``    已发货订单数 ``chuhuo=1`` ÷ 订单总数 ×100，内贸+外贸合并，接口直接返回百分数
平台推广 ROI             ``/hs/KPI/getPlatformPromotionRoi``    见下方口径说明（接口只返回新客未税金额）
复购率                   ``/hs/KPI/getRepurchaseRate``          接口直接返回百分数，用 ``month``（``YYYY-MM``）入参
退货率                   ——（``kind=metric_ratio``）             退货额 ÷ 对外出货未税销售额（净额）× 100%
======================  =====================================  ==========================================

辅助指标（为上面两个比率提供分子/原始值，自身也会出现在指标清单里）：

- **营销中心平台推广新客未税金额** ``marketing_platform_promotion_new_customer_untaxed``：
  接口 ``/hs/KPI/getPlatformPromotionRoi`` 的 ``data`` 原值（新客订单 ``is_new=1`` 的未税金额合计）；
- **营销中心退货额** ``marketing_return_amount``：接口 ``/hs/KPI/getReturnAmount`` 的 ``data``
  （退货未税金额合计，正数；接口按 ``status=522`` + 退货时间 ``refund_time`` 统计）。

两个比率指标的口径（**都是外部/文档未直接给出的，必须显式说明**）：

- **平台推广 ROI**：接口名为「ROI」，但返回值是「新客未税金额」而非比率，需由调用方结合推广费用计算。
  本系统按 ``平台推广新客未税金额 ÷ 营销中心推广费`` 计算（``ratio_scale = 1``，单位「倍」），
  分母取已有的科目余额表口径指标 ``marketing_promotion_expense``（营销中心推广费）。若业务最终定义不同
  （如分母换成平台费 ``marketing_platform_expense``、或保留原始金额不做比率），改本文件的
  ``denominator_metric_codes`` 重跑即可。
- **退货率** = 退货额 ÷ 对外出货未税销售额（净额）× 100%（用户指定口径）；分子取本脚本的
  ``marketing_return_amount``，分母取已有的 ``marketing_external_shipment_net_untaxed``
  （= 货物出货 + 设计服务收入 + 退货/退款（负数））。注意分子分母的「退回」来源不同：
  分子是 KPI 接口的退货额，分母里的退货/退款来自出货系列的 ``/hs/getReturnOrder``，
  两者口径一致与否需业务确认。

请求参数（模板按期间渲染，``now`` = 取数时点，回补时为该期间 1 日）：

- ``getOrderFulfillmentRate`` / ``getPlatformPromotionRoi`` / ``getReturnAmount``：整月闭区间
  ``dateRange``（月初 ~ 月末）；
- ``getRepurchaseRate``：**不接收 ``dateRange``**，传 ``month``（``YYYY-MM``）。

声明式维护：``SOURCE_OBJECTS`` 一个接口一条（同步任务按接口建，多个指标可共用），
``METRICS`` 一个指标一条，加指标只需在 ``METRICS`` 里加一条。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_kpi_metrics.py
    python scripts/seed_crm_kpi_metrics.py --base-url http://crmapi.yonggubox.com
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

# 与 seed_crm_marketing_metrics.py / seed_crm_shipment_metrics.py / seed_crm_push_metrics.py
# / seed_crm_worktime_metrics.py 共用同一个 CRM 连接与来源系统
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
# 复购率接口用 month（YYYY-MM），不接收 dateRange；now 回补时为该期间 1 日，strftime 即目标月份
MONTH_PARAM: dict = {"month": "{{ now.strftime('%Y-%m') }}"}

# 取数规则：由指标计算引擎解释（kind=api_scalar_amount 直接取响应 data 数值）
BASE_MEASURES = {
    "kind": "api_scalar_amount",
    "data_field": "data",
}
DIMENSIONS = {"org": False, "dept": False}

# 一个接口一条：params 是 dateRange 之外的固定请求参数，date_range=False 表示该接口不传 dateRange
SOURCE_OBJECTS = [
    {"path": "/hs/KPI/getOrderFulfillmentRate", "name": "营销中心订单履约率", "params": {}},
    {"path": "/hs/KPI/getPlatformPromotionRoi", "name": "营销中心平台推广新客未税金额", "params": {}},
    {
        "path": "/hs/KPI/getRepurchaseRate",
        "name": "营销中心复购率",
        "params": MONTH_PARAM,
        "date_range": False,
    },
    {"path": "/hs/KPI/getReturnAmount", "name": "营销中心退货额", "params": {}},
]

# 一个指标一条：measures 追加到 BASE_MEASURES，path 必须出现在 SOURCE_OBJECTS 中
METRICS = [
    {
        "code": "marketing_order_fulfillment_rate",
        "name": "营销中心订单履约率",
        "path": "/hs/KPI/getOrderFulfillmentRate",
        # 接口已返回百分数，直接取值；显式声明单位避免按默认「元」展示
        "measures": {"unit": "%"},
        "rule": "订单履约率（%）= 已发货订单数 chuhuo=1 ÷ 订单总数 × 100，内贸 + 外贸合并，"
        "按接单时间 createtime 的整月闭区间统计，接口直接返回百分数（保留 2 位小数，无订单返回 0）。",
    },
    {
        "code": "marketing_platform_promotion_new_customer_untaxed",
        "name": "营销中心平台推广新客未税金额",
        "path": "/hs/KPI/getPlatformPromotionRoi",
        "measures": {"unit": "元"},
        "rule": "平台推广新客未税金额（元）= 新客订单 is_new=1 的未税金额合计 = 内贸 "
        "SUM(receivable - taxes) + 外贸 SUM(receivable_CNY)，status=384，按接单时间 createtime 统计；"
        "接口名虽为 ROI，但返回的是金额，本指标保留原始金额，比率见「营销中心平台推广ROI」。",
    },
    {
        # 比率指标：不取数，值 = 分子指标当期值 ÷ 分母指标当期值 × ratio_scale
        "code": "marketing_platform_promotion_roi",
        "name": "营销中心平台推广ROI",
        "path": None,
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": ["marketing_platform_promotion_new_customer_untaxed"],
            "denominator_metric_codes": ["marketing_promotion_expense"],
            "ratio_scale": 1,
            "unit": "倍",
        },
        "rule": "平台推广 ROI（倍）= 平台推广新客未税金额 ÷ 营销中心推广费（当期值，分子分母同为当月）；"
        "分子是 CRM 新客未税金额、分母是科目余额表口径的推广费，分母为 0 时取 0。"
        "接口只返回新客未税金额，ROI 比率由本系统结合推广费计算，业务若另有口径需重定义分母。",
    },
    {
        "code": "marketing_repurchase_rate",
        "name": "营销中心复购率",
        "path": "/hs/KPI/getRepurchaseRate",
        "measures": {"unit": "%"},
        "rule": "复购率（%）= 当月下单且历史也下过单的客户数 ÷ 客户数分母 × 100，内贸 + 外贸去重；"
        "分母 = (月初前累计客户数 + 月末前累计客户数) / 2；按 month（YYYY-MM）入参，不接收 dateRange，"
        "且统计当月下单客户时未加 status=384 过滤（与其余接口不同），接口直接返回百分数。",
    },
    {
        "code": "marketing_return_amount",
        "name": "营销中心退货额",
        "path": "/hs/KPI/getReturnAmount",
        "measures": {"unit": "元"},
        "rule": "退货额（元）= 退货未税金额合计 = 内贸 SUM(receivable - taxes) + 外贸 SUM(receivable_CNY) "
        "+ retail_order 退货金额，均取 status=522，按退货时间 refund_time 的整月闭区间统计；"
        "接口返回正数，本指标按正数入账（退货率作分子用）。",
    },
    {
        # 比率指标：不取数，值 = 退货额 ÷ 对外出货未税销售额（净额）× 100%
        "code": "marketing_return_rate",
        "name": "营销中心退货率",
        "path": None,
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": ["marketing_return_amount"],
            "denominator_metric_codes": ["marketing_external_shipment_net_untaxed"],
            "ratio_scale": 100,
            "unit": "%",
        },
        "rule": "退货率（%）= 退货额 ÷ 对外出货未税销售额（净额）× 100%（用户指定口径）；"
        "分子取「营销中心退货额」（KPI 接口 getReturnAmount），分母取「营销中心对外出货未税销售额（净额）」"
        "（= 货物出货 + 设计服务收入 + 退货/退款（负数）），两者同为当月，分母为 0 时取 0；"
        "分母里的退货/退款来自出货系列接口，与分子的 KPI 退货额口径可能存在差异，需业务确认。",
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
    """按接口是否接收 dateRange 组装请求模板（复购率只传 month）。"""
    params = dict(spec.get("params") or {})
    if spec.get("date_range", True):
        return {**MONTH_DATE_RANGE, **params}
    return params


async def main() -> None:
    parser = argparse.ArgumentParser(description="初始化营销中心 CRM KPI 指标")
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
                "description": "CRM 订单/出货/下推/工时/KPI 接口（无需鉴权）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        # 先建接口（来源对象 + 同步任务），多个指标可共用同一接口的取数批次
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
                await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM KPI指标-{spec['name']}"))
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM KPI指标-{spec['name']}")
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.org_code = None
            job.cron_expr = args.cron
            job.request_params = request_template
            job.sync_mode = "full"
            job.status = 0
            if spec.get("date_range", True):
                job.description = f"CRM 接口 {path}，按日期取整月（闭区间）"
            else:
                job.description = f"CRM 接口 {path}，按 month（YYYY-MM）取整月（不接收 dateRange）"
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
                metric.formula = f"CRM {path} 返回的指标值（整月）"
                source_text = f"数据来源：CRM《KPI 接口文档》 {path}（GET、无需鉴权）。"
            else:
                # 比率指标不取数：去掉取数专用配置，只保留分子/分母指标清单
                measures.pop("data_field", None)
                measures.pop("source_object_code", None)
                numerator = [str(item) for item in measures.get("numerator_metric_codes") or []]
                denominator = [str(item) for item in measures.get("denominator_metric_codes") or []]
                ratio_scale = float(measures.get("ratio_scale") or 1)
                suffix = f" × {ratio_scale:g}" if ratio_scale != 1 else ""
                metric.formula = f"({' + '.join(numerator)}) ÷ ({' + '.join(denominator)}){suffix}"
                component_codes = [*numerator, *denominator]
                source_text = f"数据来源：本系统内 {len(component_codes)} 个营销中心指标当期结果（相除）；"
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
    print("营销中心 CRM KPI 指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
