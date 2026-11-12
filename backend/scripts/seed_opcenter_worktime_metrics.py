"""初始化运营中心主表「品类与流量部」工时指标 TM-01 / TM-02。

数据来源：本地企微打卡表 ``wecom_checkin_day``（由 ``scripts/wecom_backfill.py`` 同步）。
人员范围：企微部门「品类与流量部」（编码 14）及其下级部门内的在职人员，
默认排除 ``by`` 结尾的备用账号，避免同一人重复计算。

口径：
- TM-01 正常工作时间 = Σ 每天 max(0, 当日实际工时 - 1.5h 午休)
- TM-02 加班时间   = Σ 每天 max(0, 最晚打卡 - 规定下班 - 0.5h 吃饭)

用法：
    python scripts/seed_opcenter_worktime_metrics.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CATEGORY = "运营中心-主表指标"
DEPARTMENT_CODE = "14"
DEPARTMENT_NAME = "品类与流量部"
ORG_CODE = "101"

BASE_MEASURES = {
    "kind": "wecom_dept_worktime",
    "department_code": DEPARTMENT_CODE,
    "department_name": DEPARTMENT_NAME,
    "include_children": True,
    "exclude_userid_suffixes": ["by"],
    "org_code": ORG_CODE,
    "unit": "小时",
}
DIMENSIONS = {"org": True, "dept": True}

METRICS = [
    {
        "code": "TM-01",
        "name": "正常工作时间",
        "value_field": "regular",
        "formula": (
            "SUM(正常工时) WHERE 企微部门 IN (14,107,34,35) "
            "AND 在职 AND 工号 NOT LIKE '%by'"
        ),
        "rule": (
            "正常工作时间（小时）= Σ( 每天 max(0, 当天实际工作时长 − 1.5 小时午休) )；"
            "统计范围为企微「品类与流量部」（编码 14，含下级品类组/社媒组/电商组）"
            "在职人员，排除 by 结尾备用账号。"
        ),
    },
    {
        "code": "TM-02",
        "name": "加班时间",
        "value_field": "overtime",
        "formula": (
            "SUM(加班工时) WHERE 企微部门 IN (14,107,34,35) "
            "AND 在职 AND 工号 NOT LIKE '%by'"
        ),
        "rule": (
            "加班时间（小时）= Σ( max(0, 当日最晚打卡 − 规定下班时间 − 30 分钟吃饭) )，"
            "为打卡口径；统计范围同「正常工作时间」。"
        ),
    },
]


async def main() -> None:
    async with async_db_session() as db, db.begin():
        for item in METRICS:
            measures = {**BASE_MEASURES, "value_field": item["value_field"]}
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == item["code"]))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=item["code"])
                db.add(metric)
            metric.name = item["name"]
            metric.category = CATEGORY
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.formula = item["formula"]
            metric.dimensions = DIMENSIONS
            metric.measures = measures
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{item['rule']} "
                "数据来源：本地企微打卡表 wecom_checkin_day（由 scripts/wecom_backfill.py 同步）。"
                "月指标，每日重算当月，每次计算保留 calc_version 版本。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

