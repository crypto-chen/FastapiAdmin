"""初始化营销中心「外部订单库存 / 呆滞库存（>90 天）/ 海柔库存」月指标（来源对象 + 同步任务 + 指标定义）。

数据源：CRM《HASH 接口文档》 库存 · ``OutStock``（控制器
``app\\api\\controller\\accounting\\v1\\OutStock``），域名
``http://crmapi.yonggubox.com``（文档里的 ``http://crmapi.localhost.cn/api.php`` 是本地别名，
实测正式域名下取得到数）；两个接口均为 ``GET``、**无需登录/令牌**，公共参数只有
``dateRange``（按**整月闭区间**渲染：``月初 ~ 月末``）。

口径要点（详见 ``docs/核算指标系统设计.md``）：
- **外部订单库存（未税）** ``/hs/getNoChuHuo``：完工齐套但**未出货**的订单金额，
  过滤 ``status=384`` + ``has_finish=1`` + ``chuhuo=2``（未出货，与出货接口的 ``1`` 相反），
  按 **订单创建时间 ``createtime``** 落在 ``dateRange`` 内筛选，不区分批量/打样；
  金额 = 内贸 ``SUM(receivable) - SUM(taxes)`` + 外贸 ``SUM(receivable_CNY)``（未税，元）。
  **是时点快照**：同一期间每次重算取的是「当前仍未出货」的订单，历史月份会被后来的出货改写。
- **呆滞库存（>90 天，未税）** ``/hs/get90NoChuHuo``：在上面同一套过滤条件之外，
  再加 **完工/入库日期 ``finish_date`` < 今天 - 90 天**（**硬编码、不受 ``dateRange`` 影响**，
  永远以取数当天为基准），即「订单创建时间在区间内 且 完工距今超过 90 天 且 当前仍未出货」。
  结果是外部订单库存的**子集**，两者差值 ≈ 该期间 90 天内的未出货库存。
  ⚠️ 因 90 天阈值贴着「今天」，**月份越近结果越趋近 0**（刚创建的订单不可能完工超 90 天），
  该指标只在较早期月份（如当年 1-4 月）有实际数值；回补历史月份得到的也不是当时时点的快照。
- **海柔库存** ``/hs/getHaiRou``：按**入库时间**（``startMoveInTime`` / ``endMoveInTime``，
  2026-09-29 起接口支持）落在期间内的**海柔在库库存金额**：数量取海柔 ``qtyTotal``
  （在库总数，含冻结与预占，不是 ``qtyAvailable``），单位成本 = 加工成本 ``process_cost``
  + 材料成本 ``material_cost``（本地 ``yg_product_stock`` 以 ``part_name = skuCode`` 一次全表匹配，
  不受时间影响），金额 = Σ(单位成本 × ``qtyTotal``)。
  ⚠️ 口径是「**指定入库时间内的库存金额**」，不是全仓库存总额：要全仓库存需传大区间
  （如 ``2000-01-01 ~ 2030-12-31``，近似全量，入库时间为空/极早的记录会被过滤）。
  ⚠️ SKU 匹配不上时该 SKU 单价按 0 静默计入；同一 SKU 多批入库可能被重复计。

两处接口字段名坑（照抄接口实际行为）：
- 两个接口的响应都把业务值嵌在同名键里，取值路径 ``data.data``
  （``{"code":1,"msg":"ok","data":{"data":14335369.9}}``），不是 ``data``；
- 接口返回**正数**（未出货库存金额），本系统按**正数**入账（不传 ``value_scale``）。

声明式维护：``SOURCE_OBJECTS`` 一个接口一条（同步任务按接口建，多个指标可共用），
``METRICS`` 一个指标一条，加指标只需在 ``METRICS`` 里加一条。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_inventory_metrics.py
    python scripts/seed_crm_inventory_metrics.py --base-url http://crmapi.yonggubox.com
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

# 与 seed_crm_shipment_metrics.py / seed_crm_marketing_metrics.py 共用同一个 CRM 连接与来源系统
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
    {"path": "/hs/getNoChuHuo", "name": "营销中心外部订单库存（未税）", "params": {}},
    {"path": "/hs/get90NoChuHuo", "name": "营销中心呆滞库存（>90天，未税）", "params": {}},
    {"path": "/hs/getHaiRou", "name": "营销中心海柔库存", "params": {}},
]

# 一个指标一条：path 必须出现在 SOURCE_OBJECTS 中
METRICS = [
    {
        "code": "marketing_external_order_inventory_untaxed",
        "name": "营销中心外部订单库存（未税）",
        "path": "/hs/getNoChuHuo",
        # 接口把业务值嵌在同名键里，取值路径是 data.data
        "measures": {"data_field": "data.data"},
        "rule": "外部订单库存（未税）= 完工齐套但未出货的订单金额 = 内贸 SUM(receivable) - SUM(taxes) "
        "+ 外贸 SUM(receivable_CNY)；status=384、has_finish=1、chuhuo=2（未出货，与出货接口取值相反），"
        "按订单创建时间 createtime 落在期间内筛选，不区分批量/打样；"
        "为时点快照，重算取的是当前仍未出货的订单，历史月份会被后来的出货改写。",
    },
    {
        "code": "marketing_stagnant_inventory_over90_untaxed",
        "name": "营销中心呆滞库存（>90天，未税）",
        "path": "/hs/get90NoChuHuo",
        "measures": {"data_field": "data.data"},
        "rule": "呆滞库存（>90 天，未税）= 外部订单库存中完工/入库日期 finish_date 早于「今天 - 90 天」的部分；"
        "过滤条件同上（status=384、has_finish=1、chuhuo=2、createtime 落在期间内），"
        "90 天阈值硬编码、不受期间影响、永远以取数当天为基准，故月份越近结果越趋近 0，"
        "回补历史月份得到的也不是当时时点的快照；本指标是外部订单库存的子集。",
    },
    {
        "code": "marketing_hairou_inventory",
        "name": "营销中心海柔库存",
        "path": "/hs/getHaiRou",
        "measures": {"data_field": "data.data"},
        "rule": "海柔库存 = 按入库时间（startMoveInTime/endMoveInTime）落在期间内的海柔在库库存金额："
        "数量取海柔 qtyTotal（在库总数，含冻结与预占），单位成本 = 加工成本 process_cost + "
        "材料成本 material_cost（本地 yg_product_stock 以 part_name = skuCode 全表匹配，不受时间影响），"
        "金额 = Σ(单位成本 × qtyTotal)，接口取值路径 data.data；"
        "口径是「指定入库时间内的库存金额」而非全仓库存总额（全仓需传大区间），"
        "SKU 匹配不上时按 0 静默计入、同一 SKU 多批入库可能重复计。",
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
    parser = argparse.ArgumentParser(description="初始化营销中心 CRM 外部订单库存 / 呆滞库存 / 海柔库存指标")
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
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM库存指标-{spec['name']}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM库存指标-{spec['name']}")
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
            measures["source_object_code"] = path
            metric.measures = measures
            metric.formula = f"CRM {path} 返回的指标值（dateRange=整月）"
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{spec['rule']} 数据来源：CRM《HASH 接口文档》 {path}"
                "（GET、无需鉴权，dateRange 为整月闭区间）。"
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
    print("营销中心 CRM 外部订单库存 / 呆滞库存 / 海柔库存指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
