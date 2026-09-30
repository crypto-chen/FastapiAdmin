"""初始化营销中心「应收周转天数」指标。

口径（用户给定）：**应收周转天数 = 【(期初应收余额 + 期末应收余额) ÷ 2】÷
对外出货未税净额 × 天数（天数 = 30）**。

新增 2 个月指标，均为派生 / 余额口径，**不新增来源对象、不新增同步任务**：

- 营销中心平均应收余额 ``marketing_ar_balance_avg``（``kind = account_balance_filter``）
  =（期初应收余额 + 期末应收余额）÷ 2。
  来源与「营销中心应收余额」``marketing_ar_balance`` 同一张金蝶科目余额表、
  同一批同步任务（``GL_RPT_AccountBalance``，组织 100-113）：科目 ``1122`` 应收账款、
  剔除编码 100-113 的内部客户（外部客户口径一致）；
  **期初余额** = ``FBEGINDEBIT - FBEGINCREDIT``、**期末余额** = ``FENDDEBIT - FENDCREDIT``，
  即同一期间批次的「期初」与「期末」两列各取半、相加（``amount_terms`` 各带 ``sign = 0.5``）。
  因此**不需要上期批次**：科目余额表的「本期」批次本来就同时带期初与期末两列。

- 营销中心应收周转天数 ``marketing_ar_turnover_days``（``kind = metric_ratio``）
  = 平均应收余额 ÷ 对外出货未税销售额（净额）× 30（``ratio_scale = 30``，分母为 0 时取 0）。
  分母 ``marketing_external_shipment_net_untaxed``（对外出货未税净额，即 REV-01）
  由出货系列维护（``backend/scripts/seed_crm_shipment_metrics.py``），
  计算时由引擎自动按期间补齐缺结果的组成指标。

口径备注：用户原文写作「对外出货未税净额（含税）」，本脚本按系统中既有的
**对外出货未税销售额（净额）** ``marketing_external_shipment_net_untaxed`` 作分母；
如后续需要含税口径，另建一个含税净额指标、把分母编码换成它即可（只改本文件的配置）。

依赖：
- 金蝶科目余额表元数据：``python scripts/seed_account_balance_metadata.py``
- 对外出货未税净额（REV-01）：``python scripts/seed_crm_shipment_metrics.py``

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_marketing_ar_turnover_metric.py
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

# REV-01：对外出货未税销售额（净额），由出货系列维护
REV01_CODE = "marketing_external_shipment_net_untaxed"
# 天数口径：30 天（用户给定）
TURNOVER_DAYS = 30

AVG_BALANCE_CODE = "marketing_ar_balance_avg"
AVG_BALANCE_NAME = "营销中心平均应收余额"
# 期末余额指标（已存在，定义在 seed_marketing_metrics.py）
END_BALANCE_CODE = "marketing_ar_balance"

# 期初 / 期末余额各取半相加 =（期初 + 期末）÷ 2；维度为客户，剔除编码 100-113 的内部客户
AVG_BALANCE_MEASURES = {
    "kind": "account_balance_filter",
    "source_object_code": "GL_RPT_AccountBalance",
    "account_field": "FBALANCEID",
    "account_prefix": "1122",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "require_detail": True,
    "detail_is_department": False,
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
    "amount_terms": [
        {"field": "FBEGINDEBIT", "sign": 0.5},
        {"field": "FBEGINCREDIT", "sign": -0.5},
        {"field": "FENDDEBIT", "sign": 0.5},
        {"field": "FENDCREDIT", "sign": -0.5},
    ],
}

METRICS = [
    {
        "code": AVG_BALANCE_CODE,
        "name": AVG_BALANCE_NAME,
        "measures": AVG_BALANCE_MEASURES,
        "formula": (
            "SUM(0.5×(FBEGINDEBIT - FBEGINCREDIT) + 0.5×(FENDDEBIT - FENDCREDIT)) "
            "WHERE 科目=1122 应收账款 "
            "AND 客户编码 NOT IN (100,101,102,103,104,105,106,107,108,109,110,111,112,113)"
        ),
        "rule": (
            "平均应收余额 =（期初应收余额 + 期末应收余额）÷ 2：科目 1122 应收账款、"
            "剔除编码 100-113 的内部客户，期初余额取 FBEGINDEBIT - FBEGINCREDIT、"
            "期末余额取 FENDDEBIT - FENDCREDIT，两列各取半后相加；明细维度为客户"
        ),
    },
    {
        "code": "marketing_ar_turnover_days",
        "name": "营销中心应收周转天数",
        "measures": {
            "kind": "metric_ratio",
            "numerator_metric_codes": [AVG_BALANCE_CODE],
            "denominator_metric_codes": [REV01_CODE],
            "ratio_scale": TURNOVER_DAYS,
        },
        "formula": (
            f"（{AVG_BALANCE_CODE} 当期值）÷（{REV01_CODE} 当期值）× {TURNOVER_DAYS}"
        ),
        "rule": (
            "应收周转天数 =【(期初应收余额 + 期末应收余额) ÷ 2】÷ 对外出货未税净额（REV-01）× 30（天）；"
            "分子取「营销中心平均应收余额」，分母取「营销中心对外出货未税销售额（净额）」，"
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
                "数据来源：金蝶科目余额表（科目 1122 应收账款）与 CRM 出货系列指标当期结果。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()
    print("营销中心应收周转天数指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
