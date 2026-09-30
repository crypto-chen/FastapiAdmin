"""初始化「营销中心销售成本」指标。

口径（用户给定）：**结果值 = 组织 100、科目主营业务成本（6401）
本期借方发生额（FDEBIT）汇总**。

要点：

1. 来源：金蝶科目余额表（``GL_RPT_AccountBalance``，已有同步任务），
   复用「科目余额表-组织100」任务，**不新增来源对象、不新增同步任务**；
   ``measures.org_codes = ["100"]`` 让指标只取组织 100（营销中心）的数据，
   其余组织（101-113）不参与本指标。
2. 科目：``account_prefix = "6401"``（主营业务成本），
   含其下级科目（如 ``6401.01`` 主营业务成本-内销成本、``6401.03`` 主营业务成本-集团内）。
3. 金额：``FDEBIT`` 本期借方发生额。
4. 该报表是「科目行 + 核算维度行」两级结构：科目行（6401 / 6401.01 …）带科目编码但
   无核算维度，紧随其后的核算维度行科目列为空、须继承上一科目行。
   ``require_detail = True`` 跳过科目汇总行，只累加带核算维度的明细行，
   否则同一笔金额会被「科目合计行 + 明细行」重复计入一倍。
5. 维度为客户（``detail_is_department = False``），保留到客户级明细便于核对。

月指标，每日 02:30 重算当月累计值；次月 1 日重拉上月并重算，每次计算保留 ``calc_version``。

依赖：``python scripts/seed_account_balance_metadata.py``

用法：
    python scripts/seed_marketing_sales_cost_metric.py
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
from app.modules.metadata.model import StandardEntityModel  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

METRIC_CODE = "marketing_sales_cost"
METRIC_NAME = "营销中心销售成本"
# 组织 100（营销中心）
ORG_CODES = ["100"]
# 科目：主营业务成本（含 6401.01 内销成本、6401.03 集团内等下级科目）
ACCOUNT_PREFIX = "6401"

# 取数规则：由指标计算引擎解释，改口径只改这里
MEASURES = {
    "kind": "account_balance_filter",
    "source_object_code": "GL_RPT_AccountBalance",
    "account_field": "FBALANCEID",
    "account_prefix": ACCOUNT_PREFIX,
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "amount_field": "FDEBIT",
    # 跳过科目汇总行，只累加带核算维度的明细行，避免与科目行重复计入
    "require_detail": True,
    # 核算维度是客户，不作为部门拆分
    "detail_is_department": False,
    # 只取组织 100
    "org_codes": ORG_CODES,
}
DIMENSIONS = {"org": True, "dept": False}

FORMULA = "SUM(FDEBIT) WHERE 组织=100 AND 科目=6401 主营业务成本 AND 核算维度非空（跳过科目汇总行）"
DESCRIPTION = (
    "营销中心销售成本 = 组织 100（营销中心）科目 6401 主营业务成本（含 6401.01 内销成本、"
    "6401.03 集团内等下级科目）本期借方发生额 FDEBIT 汇总；取数时跳过科目汇总行，"
    "只累加带核算维度的明细行，避免同一笔金额重复计入；本指标只取组织 100，"
    "组织 101-113 不参与。来源与「营销中心费用」系列同一张金蝶科目余额表"
    "（GL_RPT_AccountBalance，科目余额表-组织100 同步任务）。"
    "月指标，每日 02:30 重算当月累计值，次月 1 日重拉上月并重算，每次计算保留 calc_version 版本。"
)


async def main() -> None:
    async with async_db_session() as db, db.begin():
        entity = (
            await db.execute(select(StandardEntityModel).where(StandardEntityModel.code == "account_balance"))
        ).scalars().first()
        if entity is None:
            raise SystemExit("未找到标准实体 account_balance，请先执行 scripts/seed_account_balance_metadata.py")

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
        metric.source_entity_id = entity.id
        metric.status = 0
        metric.description = DESCRIPTION
        await db.flush()
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
