"""初始化营销中心「出货 / 设计服务 / 退款」系列指标（连接 + 元数据 + 同步任务 + 指标定义）。

数据源：CRM《HASH 接口文档》（出货统计 OutStock、设计费/退款 XcOrder），域名
``http://crmapi.yonggubox.com``（文档里的 ``http://crmapi.localhost.cn/api.php`` 是本地别名，
四个接口实测都在正式域名下），全部 ``GET``、**无需登录/令牌**；
公共参数 ``dateRange`` 按**整月闭区间**渲染（``月初 ~ 月末``）。

口径要点（详见 ``docs/核算指标系统设计.md``）：
- 出货类（批量 / 打样）：``status=384`` + ``has_finish=1`` + ``chuhuo=1`` + ``qty>0``，
  按 **出货日期 ``chuhuo_date``** 统计（与订单/设计的下单口径不同）；
  金额 = 未税单价 × 累计出货数量（内贸 ``(receivable - taxes)/qty``、外贸 ``receivable_CNY/qty``），
  单价比 ``yg_shipments_bills`` 的 ``send_qty`` 求和。内贸/外贸在接口内已合并。
- 设计服务收入（未税）：``status=384`` 且设计费字段 > 0，**不限制** has_finish / chuhuo /
  order_type / qty，按 **订单创建时间 ``createtime``** 统计（内贸取
  ``design_remove_taxes_freight``、外贸取 ``design_cost``）。
- 退货/退款：``status=522`` 的退款订单，按 **订单创建时间 ``createtime``** 统计，
  内贸 ``SUM(receivable) - SUM(taxes)``、外贸 ``SUM(receivable_CNY)``；
  接口返回**正数**，本系统按**负数**口径入账（``value_scale = -1``），与财务「收入减项」一致。

两处接口字段名坑（照抄接口实际行为，勿按文档字段名改）：
- ``/hs/getdayangchuhuo``（打样出货）返回的键名仍是 ``piliangchuhuo``（复制批量接口时未改），
  取值路径 ``data.piliangchuhuo``；
- ``/hs/getReturnOrder``（退款）返回值嵌了一层同名键，取值路径 ``data.data``。

另有 2 个汇总指标（``kind = metric_sum``）与 1 个折算指标（``kind = metric_scale``），
三者自身都不取数、只用既有指标的当期结果：

- **营销中心货物出货（未税）** = 批量出货（未税）+ 打样出货（未税）+ 零售出货（未税）。
  CRM 侧没有零售出货接口（``getlingshouchuhuo`` 等 16 个候选路径实测均 404），
  **零售出货（未税）取本系统已有的聚水潭指标「零售出库未税总金额」
  ``retail_outbound_untaxed_amount``**（口径见 ``docs/聚水潭对接说明.md``）；
  若后续 CRM 开放零售出货接口，把该项替换为对应指标编码即可。
- **营销中心对外出货未税销售额（净额）** = 货物出货（未税）+ 设计服务收入（未税）+ 退货/退款（负数），
  即把设计服务并入出货口径、再减掉退款，得到对外销售的未税净额。
- **营销中心总收益（营销结算收入）** = 对外出货未税销售额（净额）REV-01 × 10%（``scale = 0.1``）。
- **材料成本（列示）/ 制造费用-变动（列示）/ 制造费用-固定（列示）**：报表列示口径，
  分别 = REV-01 × 20% / 8% / 6%（``scale = 0.2 / 0.08 / 0.06``），**仅列示、不是实际成本核算**。
- **营销中心产品成本小计（列示）** = 上面三项列示成本之和（即 REV-01 × 34%），仅列示。

声明式维护：``SOURCE_OBJECTS`` 一个接口一条（同步任务按接口建，多个指标可共用），
``METRICS`` 一个指标一条（``path = None`` 表示汇总指标，不建来源对象与同步任务），
加指标只需在 ``METRICS`` 里加一条。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_shipment_metrics.py
    python scripts/seed_crm_shipment_metrics.py --base-url http://crmapi.yonggubox.com
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

# 与 seed_crm_marketing_metrics.py 共用同一个 CRM 连接与来源系统
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

BASE_MEASURES = {"kind": "api_scalar_amount"}
DIMENSIONS = {"org": False, "dept": False}

# 一个接口一条：params 是 dateRange 之外的固定请求参数（本系列接口无额外参数）
SOURCE_OBJECTS = [
    {"path": "/hs/getpiliangchuhuo", "name": "营销中心批量出货（未税）", "params": {}},
    {"path": "/hs/getdayangchuhuo", "name": "营销中心打样出货（未税）", "params": {}},
    {"path": "/hs/getShejifei", "name": "营销中心设计服务收入（未税）", "params": {}},
    {"path": "/hs/getReturnOrder", "name": "营销中心退货/退款（负数）", "params": {}},
]

# 一个指标一条：measures 追加到 BASE_MEASURES，path 必须出现在 SOURCE_OBJECTS 中
METRICS = [
    {
        "code": "marketing_batch_shipment_untaxed",
        "name": "营销中心批量出货（未税）",
        "path": "/hs/getpiliangchuhuo",
        "measures": {"data_field": "data.piliangchuhuo"},
        "rule": "批量订单（order_type=1）已出货未税金额 = 内贸 ((receivable - taxes)/qty)×Σsend_qty "
        "+ 外贸 (receivable_CNY/qty)×Σsend_qty；status=384、has_finish=1、chuhuo=1、qty>0，"
        "按出货日期 chuhuo_date 统计。",
    },
    {
        "code": "marketing_sample_shipment_untaxed",
        "name": "营销中心打样出货（未税）",
        "path": "/hs/getdayangchuhuo",
        # 接口字段名沿用批量接口（data.piliangchuhuo），属接口实际行为，勿改
        "measures": {"data_field": "data.piliangchuhuo"},
        "rule": "打样订单（order_type=2）已出货未税金额 = 内贸 ((receivable - taxes)/qty)×Σsend_qty "
        "+ 外贸 (receivable_CNY/qty)×Σsend_qty；status=384、has_finish=1、chuhuo=1、qty>0，"
        "按出货日期 chuhuo_date 统计；返回字段名沿用批量的 piliangchuhuo。",
    },
    {
        "code": "marketing_design_service_income_untaxed",
        "name": "营销中心设计服务收入（未税）",
        "path": "/hs/getShejifei",
        "measures": {"data_field": "data.shejifei"},
        "rule": "设计服务收入（未税）= 内贸 SUM(design_remove_taxes_freight) + 外贸 SUM(design_cost)，"
        "status=384 且设计费字段 > 0，不限制批量/打样、不要求已出货或已完结，按订单创建时间 createtime 统计。",
    },
    {
        "code": "marketing_return_refund_untaxed",
        "name": "营销中心退货/退款（负数）",
        "path": "/hs/getReturnOrder",
        # 接口返回正数，本系统按负数口径入账
        "measures": {"data_field": "data.data", "value_scale": -1},
        "rule": "退货/退款（负数）= -1 ×（内贸 SUM(receivable) - SUM(taxes) + 外贸 SUM(receivable_CNY)）；"
        "status=522 的退款订单，按订单创建时间 createtime 统计（非退款发生时间）。",
    },
    {
        # 汇总指标：不取数，合计下面 3 个出货类指标当期结果。
        # 零售出货口径已与业务确认：CRM 无零售出货接口，取本系统已有的聚水潭指标
        # 「零售出库未税总金额」`retail_outbound_untaxed_amount`（销售出库单，非零售订单接口）。
        "code": "marketing_goods_shipment_untaxed",
        "name": "营销中心货物出货（未税）",
        "path": None,
        "measures": {
            "kind": "metric_sum",
            "component_metric_codes": [
                "marketing_batch_shipment_untaxed",
                "marketing_sample_shipment_untaxed",
                "retail_outbound_untaxed_amount",
            ],
        },
        "rule": "货物出货（未税）= 批量出货（未税）+ 打样出货（未税）+ 零售出货（未税）；"
        "零售出货取聚水潭「零售出库未税总金额」（CRM 无零售出货接口）。",
    },
    {
        # 汇总指标：不取数。含一个已汇总指标（货物出货）和一个负数指标（退货/退款），
        # 引擎按「组成指标最新版本的组织合计行」相加，负值同样直接相加。
        "code": "marketing_external_shipment_net_untaxed",
        "name": "营销中心对外出货未税销售额（净额）",
        "path": None,
        "measures": {
            "kind": "metric_sum",
            "component_metric_codes": [
                "marketing_goods_shipment_untaxed",
                "marketing_design_service_income_untaxed",
                "marketing_return_refund_untaxed",
            ],
        },
        "rule": "对外出货未税销售额（净额）= 货物出货（未税）+ 设计服务收入（未税）+ 退货/退款（负数）；"
        "退货/退款已在自身指标内取负，此处直接相加。",
    },
    {
        # 折算指标：不取数，值 = 组成指标当期值 × scale（对外出货未税净额 × 10%）
        "code": "marketing_total_income_settlement",
        "name": "营销中心总收益（营销结算收入）",
        "path": None,
        "measures": {
            "kind": "metric_scale",
            "component_metric_codes": ["marketing_external_shipment_net_untaxed"],
            "scale": 0.1,
        },
        "rule": "总收益（营销结算收入）= 对外出货未税销售额（净额）× 10%。",
    },
    {
        # 列示类折算指标：只为报表列示，值 = 对外出货未税净额 × 固定百分比（非实际成本核算）
        "code": "marketing_material_cost_listed",
        "name": "营销中心材料成本（列示）",
        "path": None,
        "measures": {
            "kind": "metric_scale",
            "component_metric_codes": ["marketing_external_shipment_net_untaxed"],
            "scale": 0.2,
        },
        "rule": "材料成本（列示，变动）= 对外出货未税销售额（净额）REV-01 × 20%，仅列示、非实际材料成本。",
    },
    {
        "code": "marketing_overhead_variable_listed",
        "name": "营销中心制造费用-变动（列示）",
        "path": None,
        "measures": {
            "kind": "metric_scale",
            "component_metric_codes": ["marketing_external_shipment_net_untaxed"],
            "scale": 0.08,
        },
        "rule": "制造费用-变动（列示）= 对外出货未税销售额（净额）REV-01 × 8%，仅列示、非实际制造费用。",
    },
    {
        "code": "marketing_overhead_fixed_listed",
        "name": "营销中心制造费用-固定（列示）",
        "path": None,
        "measures": {
            "kind": "metric_scale",
            "component_metric_codes": ["marketing_external_shipment_net_untaxed"],
            "scale": 0.06,
        },
        "rule": "制造费用-固定（列示）= 对外出货未税销售额（净额）REV-01 × 6%，仅列示、非实际制造费用。",
    },
    {
        # 列示类汇总指标：不取数，合计上面三项列示成本
        "code": "marketing_product_cost_subtotal_listed",
        "name": "营销中心产品成本小计（列示）",
        "path": None,
        "measures": {
            "kind": "metric_sum",
            "component_metric_codes": [
                "marketing_material_cost_listed",
                "marketing_overhead_variable_listed",
                "marketing_overhead_fixed_listed",
            ],
        },
        "rule": "产品成本小计（列示）= 材料成本（列示）+ 制造费用-变动（列示）+ 制造费用-固定（列示），"
        "即 REV-01 × (20% + 8% + 6%)；仅列示、非实际成本核算。",
    },
    {
        # 比率指标：不取数，值 = 列示口径制造成本 ÷ 对外出货未税销售额（净额）
        "code": "marketing_manufacturing_cost_rate",
        "name": "营销中心制造成本率（材料及能源）",
        "path": None,
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": ["marketing_product_cost_subtotal_listed"],
            "denominator_metric_codes": ["marketing_external_shipment_net_untaxed"],
            "ratio_scale": 100,
        },
        "rule": "制造成本率（材料及能源）= 产品成本小计（列示）÷ 对外出货未税销售额（净额）× 100%（百分数）；"
        "分子是列示口径（REV-01 × 34%），故该比率目前恒为 34%，只有列示比例调整时才会变；"
        "仅列示、不是实际制造成本率；分母为 0 时取 0。",
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
    parser = argparse.ArgumentParser(description="初始化营销中心 CRM 出货/设计服务/退款指标")
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
                "description": "CRM 订单/出货/报价接口（无需鉴权）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        # 先建接口（来源对象 + 同步任务）
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
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM出货指标-{spec['name']}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM出货指标-{spec['name']}")
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
            measures = {**BASE_MEASURES, **spec.get("measures", {})}
            if path:
                measures["source_object_code"] = path
                metric.formula = f"CRM {path} 返回的指标值（dateRange=整月）"
                source_text = f"数据来源：CRM《HASH 接口文档》 {path}（GET、无需鉴权，dateRange 为整月闭区间）。"
            else:
                # 汇总/折算/比率指标不取数：去掉取数专用配置，只保留组成指标清单
                measures.pop("data_field", None)
                measures.pop("source_object_code", None)
                kind = str(measures.get("kind"))
                if kind == "metric_ratio":
                    numerator = [str(code) for code in measures.get("numerator_metric_codes") or []]
                    denominator = [str(code) for code in measures.get("denominator_metric_codes") or []]
                    ratio_scale = float(measures.get("ratio_scale") or 1)
                    suffix = f" × {ratio_scale:g}" if ratio_scale != 1 else ""
                    metric.formula = f"({' + '.join(numerator)}) ÷ ({' + '.join(denominator)}){suffix}"
                    source_text = "数据来源：本系统内下列指标当期结果相除；"
                elif kind == "metric_scale":
                    component_codes = list(measures.get("component_metric_codes") or [])
                    metric.formula = f"({component_codes[0]} 当期值) × {measures.get('scale')}"
                    source_text = "数据来源：本系统内下列指标的当期结果按系数折算；"
                else:
                    component_codes = list(measures.get("component_metric_codes") or [])
                    metric.formula = "SUM(" + " + ".join(component_codes) + ")"
                    source_text = "数据来源：本系统内下列出货类指标的当期结果合计；"
            metric.measures = measures
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{spec['rule']} {source_text}月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

        print(f"CRM 连接 id={connection.id}，来源系统 id={system.id}，同步任务 {job_ids}")

    for job_id in job_ids:
        job = await _load_job(job_id)
        if job is not None:
            register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心 CRM 出货/设计服务/退款指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
