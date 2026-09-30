"""初始化营销中心「工时」系列指标（连接 + 元数据 + 同步任务 + 指标定义）。

数据源：CRM《HASH 接口文档》工时统计（``QwApi``），域名
``http://crmapi.yonggubox.com``（文档里的 ``http://crmapi.localhost.cn/api.php`` 是本地别名，
实测正式域名下同样可用），``GET``、**无需登录/令牌**；公共参数 ``dateRange`` 按**整月闭区间**
渲染（``月初 ~ 月末``）。

口径要点（详见 ``docs/核算指标系统设计.md``）：
- 数据来源是**实时调用企业微信打卡日报**（``checkin/getcheckin_daydata``，不查 CRM 本地库），
  统计人员 = 企微通讯录里 ``yg_admin.status='normal'``（在职）且工号以 ``YG20`` 开头的
  **营销人员**（车间 ``YG10xxx`` 不纳入）；取不到人接口直接报错。
- ``data.regularWorkHours`` **正常工作时间（小时）**：按天扣午休
  = Σ( 每天 max(0, 当天实际工作时长 − 1.5 小时) )，受迟到早退影响。
- ``data.overtimeHours`` **加班时间（小时）**：打卡口径
  = Σ( max(0, 当日最晚打卡时间 − 规定下班时间 − 30 分钟吃饭时间) )，**不是**加班审批口径；
  跨夜打卡（次日凌晨）仍计入加班，接口用 ``crossDayCount`` 标记需人工复核的条数。
- 接口对历史区间缓存 24 小时、含今天的区间缓存 10 分钟；怀疑数据不对时传 ``refresh=1``
  跳过缓存强制重拉（本系统按整月取数，取的都是历史区间）。

另有 1 个**汇总指标**（``kind = metric_sum``，自身不取数）：
**营销中心总劳动时间** = 正常工作时间 + 加班时间（当期结果相加，计算前先补齐缺结果的组成指标）。

三个指标都是**公司整体口径**（接口只返回营销中心全体合计，不按组织/部门拆分）。
接口路径即来源对象 ``code``，两个明细指标共用同一个接口的取数批次。

声明式维护：``SOURCE_OBJECTS`` 一个接口一条，``METRICS`` 一个指标一条，
加指标只需在 ``METRICS`` 里加一条。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_worktime_metrics.py
    python scripts/seed_crm_worktime_metrics.py --base-url http://crmapi.yonggubox.com
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

# 与 seed_crm_marketing_metrics.py / seed_crm_shipment_metrics.py / seed_crm_push_metrics.py 共用
# 同一个 CRM 连接与来源系统
CONNECTION_NAME = "CRM 默认连接"
SOURCE_SYSTEM_CODE = "crm"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30

# 整月闭区间（day=1 ~ 当月最后一天）；{{ }} 由元数据同步任务渲染，now = 取数时点（回补时为该期间 1 日）
MONTH_DATE_RANGE: dict = {
    "dateRange": [
        "{{ now.replace(day=1).strftime('%Y-%m-%d') }}",
        "{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d') }}",
    ]
}

# 取数规则：由指标计算引擎解释（kind=api_scalar_amount 直接取响应 data 里的字段）
BASE_MEASURES = {
    "kind": "api_scalar_amount",
    "data_field": "data",
}
DIMENSIONS = {"org": False, "dept": False}

# 一个接口一条：params 是 dateRange 之外的固定请求参数（本接口无额外参数）
SOURCE_OBJECTS = [
    {"path": "/hs/getWorkTime", "name": "营销中心工时统计（企微打卡）", "params": {}},
]

# 一个指标一条：measures 追加到 BASE_MEASURES，path 必须出现在 SOURCE_OBJECTS 中。
# 工时单位是「小时」（非金额），必须显式声明 unit，否则开放接口/文档会按默认「元」展示。
METRICS = [
    {
        "code": "marketing_regular_work_hours",
        "name": "营销中心正常工作时间",
        "path": "/hs/getWorkTime",
        "measures": {"data_field": "data.regularWorkHours", "unit": "小时"},
        "rule": "正常工作时间（小时）= Σ( 每天 max(0, 当天实际工作时长 − 1.5 小时午休) )，按天扣午休而非"
        "「总工时 − 总天数 × 1.5h」；当天工时为 0（缺卡/只打一次卡）不计入。统计范围为企业微信打卡里"
        "工号以 YG20 开头的在职营销人员（车间 YG10xxx 不纳入），受迟到早退影响，按打卡统计区间 dateRange 取数。",
    },
    {
        "code": "marketing_overtime_hours",
        "name": "营销中心加班时间",
        "path": "/hs/getWorkTime",
        "measures": {"data_field": "data.overtimeHours", "unit": "小时"},
        "rule": "加班时间（小时）= Σ( max(0, 当日最晚打卡时间 − 规定下班时间 − 30 分钟吃饭时间) )，"
        "为**打卡口径**（超过 18 点后扣 30 分钟），不是加班审批口径；跨夜打卡（次日凌晨）仍计入加班，"
        "可人工复核的跨夜条数见接口 overtime.crossDayCount。统计范围同「营销中心正常工作时间」。",
    },
    {
        # 汇总指标：不取数，直接合计上面两个工时指标的当期结果
        "code": "marketing_total_labor_hours",
        "name": "营销中心总劳动时间",
        "path": None,
        "measures": {
            "kind": "metric_sum",
            "component_metric_codes": [
                "marketing_regular_work_hours",
                "marketing_overtime_hours",
            ],
            "unit": "小时",
        },
        "rule": "总劳动时间（小时）= 正常工作时间 + 加班时间，两者均为企微打卡口径、同为「营销中心"
        "（工号 YG20 开头的在职营销人员）」合计，故直接相加（本月未满月时是当月累计值）；"
        "本指标自身不取数，由组成指标当期结果汇总，组成指标口径变化后需重算本指标。",
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
    parser = argparse.ArgumentParser(description="初始化营销中心 CRM 工时指标")
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
                "description": "CRM 订单/出货/下推/工时接口（无需鉴权）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        # 先建接口（来源对象 + 同步任务）：两个指标共用同一个接口的取数批次
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
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM工时指标-{spec['name']}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM工时指标-{spec['name']}")
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.org_code = None
            job.cron_expr = args.cron
            job.request_params = request_template
            job.sync_mode = "full"
            job.status = 0
            job.description = f"CRM 接口 {path}，按日期取整月（闭区间；企微日报，历史区间上游缓存 24 小时）"
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
                metric.formula = f"CRM {path} 返回的{spec['name']}（小时，dateRange=整月）"
                source_text = (
                    f"数据来源：CRM《HASH 接口文档》 {path}（GET、无需鉴权，dateRange 为整月闭区间，"
                    "实时调企微打卡日报、非 CRM 本地库）。"
                )
            else:
                # 汇总指标不取数：去掉取数专用配置，只保留组成指标清单
                measures.pop("data_field", None)
                measures.pop("source_object_code", None)
                component_codes = [str(item) for item in measures.get("component_metric_codes") or []]
                metric.formula = "SUM(" + " + ".join(component_codes) + ")"
                source_text = f"数据来源：本系统内 {len(component_codes)} 个营销中心工时指标当期结果合计；"
            metric.measures = measures
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{spec['rule']} "
                f"{source_text}"
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
    print("营销中心 CRM 工时指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
