"""初始化营销中心「应付周转天数」指标。

口径（用户给定）：**应付周转天数 = 【(期初应付账款 + 期末应付账款) ÷ 2】÷
当期采购入库金额（含税）× 天数（天数 = 30）**。

新增 2 个月指标，均为派生 / 余额口径，**不新增来源对象、不新增同步任务**：

- 营销中心平均应付余额 ``marketing_ap_balance_avg``（``kind = account_balance_filter``）
  =（期初应付余额 + 期末应付余额）÷ 2。
  来源与「营销中心应付余额」``marketing_ap_balance`` 同一张金蝶科目余额表、
  同一批同步任务（``GL_RPT_AccountBalance``，组织 100-113）：科目 ``2202`` 应付账款、
  剔除编码 100-113 的内部组织（外部往来单位口径一致）；
  应付账款是贷方科目，**期初余额** = ``FBEGINCREDIT - FBEGINDEBIT``、
  **期末余额** = ``FENDCREDIT - FENDDEBIT``，两个方向的列各带 ``sign = 0.5`` 相加，
  即期初与期末各取半。科目余额表的「本期」批次本来就同时带期初与期末两列，
  因此**不需要上期批次**。

- 营销中心应付周转天数 ``marketing_ap_turnover_days``（``kind = metric_ratio``）
  = 平均应付余额 ÷ 当期采购入库金额（含税）× 30（``ratio_scale = 30``，分母为 0 时取 0）。
  分母 ``marketing_purchase_inbound_incl_tax``（当期营销中心采购入库金额（含税））
  由采购入库系列维护（``backend/scripts/seed_marketing_purchase_inbound_metric.py``），
  计算时由引擎自动按期间补齐缺结果的组成指标。

依赖：
- 金蝶科目余额表元数据：``python scripts/seed_account_balance_metadata.py``
- 采购入库金额（含税）：``python scripts/seed_marketing_purchase_inbound_metric.py``

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_marketing_ap_turnover_metric.py
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

DIMENSIONS = {"org": False, "dept": False}

# 分母：当期营销中心采购入库金额（含税），由采购入库系列维护
PURCHASE_INBOUND_CODE = "marketing_purchase_inbound_incl_tax"
# 天数口径：30 天（用户给定）
TURNOVER_DAYS = 30

AVG_BALANCE_CODE = "marketing_ap_balance_avg"
AVG_BALANCE_NAME = "营销中心平均应付余额"

# 期初 / 期末余额各取半相加 =（期初 + 期末）÷ 2；
# 应付账款为贷方科目，余额 = 贷方 - 借方；维度为往来单位，剔除编码 100-113 的内部组织
AVG_BALANCE_MEASURES = {
    "kind": "account_balance_filter",
    "source_object_code": "GL_RPT_AccountBalance",
    "account_field": "FBALANCEID",
    "account_prefix": "2202",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "require_detail": True,
    "detail_is_department": False,
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
    "amount_terms": [
        {"field": "FBEGINCREDIT", "sign": 0.5},
        {"field": "FBEGINDEBIT", "sign": -0.5},
        {"field": "FENDCREDIT", "sign": 0.5},
        {"field": "FENDDEBIT", "sign": -0.5},
    ],
}

METRICS = [
    {
        "code": AVG_BALANCE_CODE,
        "name": AVG_BALANCE_NAME,
        "measures": AVG_BALANCE_MEASURES,
        "formula": (
            "SUM(0.5×(FBEGINCREDIT - FBEGINDEBIT) + 0.5×(FENDCREDIT - FENDDEBIT)) "
            "WHERE 科目=2202 应付账款 "
            "AND 往来单位编码 NOT IN (100,101,102,103,104,105,106,107,108,109,110,111,112,113)"
        ),
        "rule": (
            "平均应付余额 =（期初应付余额 + 期末应付余额）÷ 2：科目 2202 应付账款、"
            "剔除编码 100-113 的内部组织，期初余额取 FBEGINCREDIT - FBEGINDEBIT、"
            "期末余额取 FENDCREDIT - FENDDEBIT，两列各取半后相加；明细维度为往来单位"
        ),
    },
    {
        "code": "marketing_ap_turnover_days",
        "name": "营销中心应付周转天数",
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": [AVG_BALANCE_CODE],
            "denominator_metric_codes": [PURCHASE_INBOUND_CODE],
            "ratio_scale": TURNOVER_DAYS,
        },
        "formula": (
            f"（{AVG_BALANCE_CODE} 当期值）÷（{PURCHASE_INBOUND_CODE} 当期值）× {TURNOVER_DAYS}"
        ),
        "rule": (
            "应付周转天数 =【(期初应付账款 + 期末应付账款) ÷ 2】÷ 当期采购入库金额（含税）× 30（天）；"
            "分子取「营销中心平均应付余额」，分母取「当期营销中心采购入库金额（含税）」，"
            "公司整体口径、分母为 0 时取 0"
        ),
    },
]


async def main() -> None:
    async with async_db_session() as db, db.begin():
        entity = (
            await db.execute(select(StandardEntityModel).where(StandardEntityModel.code == "account_balance"))
        ).scalars().first()
        if entity is None:
            raise SystemExit("未找到标准实体 account_balance，请先执行 scripts/seed_account_balance_metadata.py")

        for spec in METRICS:
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == spec["code"]))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=spec["code"])
                db.add(metric)
            measures = dict(spec["measures"])
            metric.name = spec["name"]
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.formula = spec["formula"]
            metric.dimensions = DIMENSIONS
            metric.measures = measures
            # 余额类指标挂在科目余额表标准实体上；比率指标自身不取数
            metric.source_entity_id = entity.id if measures.get("kind") == "account_balance_filter" else None
            metric.status = 0
            metric.description = (
                f"{spec['rule']}；月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本；"
                "数据来源：金蝶科目余额表（科目 2202 应付账款）与采购入库金额（含税）当期结果。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()
    print("营销中心应付周转天数指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
