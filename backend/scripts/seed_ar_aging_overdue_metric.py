"""初始化「应收账款逾期应收」与「营销中心逾期率」指标（来源：金蝶《应收款账龄分析表》）。

口径（用户给定）：

1. **逾期应收 = ERP 应收款账龄表中账龄 30 天以上的未收款汇总**（``marketing_ar_overdue``）。
2. **营销中心逾期率 = 逾期应收 ÷ 应收余额 × 100%**（``marketing_overdue_rate``，
   比率指标 ``kind = metric_ratio``：分子 = 逾期应收，分母 = 营销中心应收余额
   ``marketing_ar_balance``（期末余额），分母为 0 时取 0，公司整体口径）。

实现方式：复用账龄表取数执行器（``kind = ar_aging_provision``），把账龄区间比例改成
「30 天以内 0、30 天以上 100%」——区间比例乘金额后求和即等价于「汇总 30 天以上未收款」：

    0-30 天 0%、31-60 天 100%、61-90 天 100%、
    91-180 天 100%、181-365 天 100%、365 天以上 100%

因此**不改计算引擎**，只新增指标定义；来源对象、字段、14 个组织的实时取数任务
全部复用「营销中心坏账计提」（``backend/scripts/seed_ar_aging_metric.py``）：

- 来源对象 ``AR_AgingAnalysis``（按单据 ``FByBill=true``），金额 = 「尚未收款金额（本位币）
  ``FBalanceAmt``」；账龄基准默认到期日 ``FEndDate``，缺失退化为业务日期 ``FDate``；
  账龄截止日 = 期末日（当期取今天）。
- 计入口径 ``netting = customer``：先按往来单位汇总净值（应收与预收相抵，账龄表的
  收款单/平台待清分等负数行一并参与相抵），**客户净额 ≤ 0 的不计入**；
  净额为正的客户再按各账龄档取「31 天及以上」部分的未收款相加。
  切换成逐单口径只需把 ``netting`` 改成 ``"bill"``（并可选 ``skip_negative_amount``）。
- 剔除编码 100-113 的内部客户，与「营销中心应收余额」「营销中心坏账计提」口径一致。
- 明细维度为往来单位（客户）：每个客户的指标值 = 该客户账龄 30 天以上的未收款。

注意：该来源对象**不落同步批次**（一次全量约 7MB/组织），计算时由引擎按组织并发实时取数，
所以首次计算 / 每次重算都会实时连金蝶，耗时比科目余额表类指标长。

依赖（先执行）：
    python scripts/seed_ar_aging_metric.py      # 账龄表来源对象、字段、实时取数组织任务
    python scripts/seed_marketing_metrics.py    # 分母「营销中心应收余额」marketing_ar_balance

用法：
    python scripts/seed_ar_aging_overdue_metric.py
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
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    SourceObjectModel,
    StandardEntityModel,
)
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

# 复用坏账计提脚本建立的来源对象与标准实体
SOURCE_OBJECT_CODE = "AR_AgingAnalysis"
STANDARD_ENTITY_CODE = "ar_aging_analysis"

METRIC_CODE = "marketing_ar_overdue"
METRIC_NAME = "应收账款逾期应收"
# 逾期阈值：账龄 > 30 天（即 31 天及以上）计入
OVERDUE_DAYS = 30

# 区间比例：30 天以内 0、30 天以上 100% —— 比例 × 金额求和即「30 天以上未收款汇总」
BUCKETS = [
    {"max_days": OVERDUE_DAYS, "rate": 0.0},
    {"max_days": 60, "rate": 1.0},
    {"max_days": 90, "rate": 1.0},
    {"max_days": 180, "rate": 1.0},
    {"max_days": 365, "rate": 1.0},
    {"max_days": None, "rate": 1.0},
]

MEASURES = {
    "kind": "ar_aging_provision",
    "source_object_code": SOURCE_OBJECT_CODE,
    # 按往来单位取净值，客户净额 ≤ 0 的不计入（账龄表里的负数行参与相抵）
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

FORMULA = (
    "SUM(客户净额 WHERE 账龄 > 30 天) WHERE 来源=应收款账龄分析表(按单据) "
    "AND 客户净额 > 0 AND 往来单位 NOT IN (100,101,102,103,104,105,106,107,108,109,110,111,112,113)"
)
DESCRIPTION = (
    "应收账款逾期应收 = 金蝶《应收款账龄分析表》按单据的「尚未收款金额（本位币）」中"
    "**账龄 30 天以上（31 天及以上）**部分的汇总。先按往来单位汇总净值（应收与预收相抵），"
    "客户净额 ≤ 0 的不计入；净额为正的客户按账龄档取 31 天以上部分的未收款相加"
    "（区间比例 30 天以内 0、30 天以上 100%）。账龄基准默认到期日（无到期日按业务日期），"
    "剔除编码 100-113 的内部客户，明细维度为往来单位（客户）。账龄截止日 = 期末日（当期取今天）；"
    "月指标，每日重算当月数值，每次计算保留 calc_version 版本；该指标实时连金蝶取数，不落同步批次。"
)

# 分母：营销中心应收余额（期末余额，定义在 seed_marketing_metrics.py）
AR_BALANCE_CODE = "marketing_ar_balance"

RATE_METRIC_CODE = "marketing_overdue_rate"
RATE_METRIC_NAME = "营销中心逾期率"
RATE_MEASURES = {
    "kind": "metric_ratio",
    "numerator_metric_codes": [METRIC_CODE],
    "denominator_metric_codes": [AR_BALANCE_CODE],
    # 比率放大 100 倍输出百分数（如 0.85 → 85%）
    "ratio_scale": 100,
}
RATE_FORMULA = f"（{METRIC_CODE} 当期值）÷（{AR_BALANCE_CODE} 当期值）× 100"
RATE_DESCRIPTION = (
    "营销中心逾期率 = 应收账款逾期应收 ÷ 营销中心应收余额 × 100%。"
    "分子 = 金蝶《应收款账龄分析表》账龄 30 天以上的未收款汇总（剔除内部客户、按客户净值）；"
    "分母 = 科目余额表 1122 应收账款外部客户期末余额（借方 - 贷方）。"
    "公司整体口径（分子分母都取各组织合计），分母为 0 时取 0；"
    "月指标，每日重算当月数值，每次计算保留 calc_version 版本；计算前引擎会自动补齐分子/分母的当期结果。"
)

# 一个指标一条；``entity_bound`` 为真表示挂在账龄分析表标准实体上（否则为自身不取数的派生指标）
METRICS = [
    {
        "code": METRIC_CODE,
        "name": METRIC_NAME,
        "measures": MEASURES,
        "formula": FORMULA,
        "description": DESCRIPTION,
        "entity_bound": True,
    },
    {
        "code": RATE_METRIC_CODE,
        "name": RATE_METRIC_NAME,
        "measures": RATE_MEASURES,
        "formula": RATE_FORMULA,
        "description": RATE_DESCRIPTION,
        "entity_bound": False,
    },
]


async def main() -> None:
    async with async_db_session() as db, db.begin():
        source_object = (
            await db.execute(select(SourceObjectModel).where(SourceObjectModel.code == SOURCE_OBJECT_CODE))
        ).scalars().first()
        if source_object is None:
            raise SystemExit(
                f"未找到来源对象 {SOURCE_OBJECT_CODE}，请先执行 scripts/seed_ar_aging_metric.py"
            )
        entity = (
            await db.execute(select(StandardEntityModel).where(StandardEntityModel.code == STANDARD_ENTITY_CODE))
        ).scalars().first()
        if entity is None:
            raise SystemExit(
                f"未找到标准实体 {STANDARD_ENTITY_CODE}，请先执行 scripts/seed_ar_aging_metric.py"
            )
        job_count = len(
            (
                await db.execute(
                    select(MetaSyncJobModel.id).where(
                        MetaSyncJobModel.source_object_id == source_object.id,
                        MetaSyncJobModel.status == 0,
                    )
                )
            ).all()
        )
        if not job_count:
            raise SystemExit(
                f"来源对象 {SOURCE_OBJECT_CODE} 下没有启用中的同步任务，"
                "请先执行 scripts/seed_ar_aging_metric.py 登记组织与结算组织内码"
            )

        for spec in METRICS:
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == spec["code"]))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=spec["code"])
                db.add(metric)
            metric.name = spec["name"]
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.formula = spec["formula"]
            metric.dimensions = DIMENSIONS
            metric.measures = dict(spec["measures"])
            metric.source_entity_id = entity.id if spec["entity_bound"] else None
            metric.status = 0
            metric.description = spec["description"]
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")
        print(f"复用来源对象 id={source_object.id} code={source_object.code}，实时取数组织任务 {job_count} 个")

    await async_engine.dispose()
    print("应收账款逾期应收 / 营销中心逾期率指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
