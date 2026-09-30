"""初始化营销中心系列指标定义（销售费用 6601 下的费用项目 + 应收/应付余额）。

口径：所有组织、科目 6601（销售费用）、核算维度名称含指定费用项目的
本期借方发生额（FDEBIT）汇总。月指标，每日重算当月累计值。

另含余额类指标（来源同一张金蝶科目余额表 ``GL_RPT_AccountBalance``）：

- ``marketing_ar_balance`` 营销中心应收余额 = 科目 ``1122`` 应收账款、
  剔除编码 100-113 的内部客户，期末借方余额（``FENDDEBIT - FENDCREDIT``）。
- ``marketing_ap_balance`` 营销中心应付余额 = 科目 ``2202`` 应付账款、
  剔除编码 100-113 的内部往来单位，期末贷方余额（``FENDCREDIT - FENDDEBIT``）。

新增同类指标只需在 ``METRIC_DEFS`` 里加一条，不改代码。

用法：
    python scripts/seed_marketing_metrics.py
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

# 取数规则：由指标计算引擎解释，改口径只改这里。
BASE_MEASURES = {
    "kind": "account_balance_filter",
    "source_object_code": "GL_RPT_AccountBalance",
    "account_field": "FBALANCEID",
    "account_prefix": "6601",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "amount_field": "FDEBIT",
}
DIMENSIONS = {"org": True, "dept": True}

METRIC_DEFS = [
    {
        "code": "marketing_office_expense",
        "name": "营销中心办公费用",
        "detail_name_contains": ["办公费"],
    },
    {
        "code": "marketing_travel_expense",
        "name": "营销中心差旅费用",
        # 差旅口径含三种维度写法：差旅费 / 交通费 / 交通差旅
        "detail_name_contains": ["差旅费", "交通费", "交通差旅"],
    },
    {
        "code": "marketing_vehicle_expense",
        "name": "营销中心车辆费用",
        # 车辆口径按费用项目精确匹配，避免误纳「推广店铺直通车」等同含"车"字的广告费用
        "detail_name_contains": ["车辆维修费", "车辆年审保养保险", "车油卡充值", "停车费"],
    },
    {
        "code": "marketing_low_value_consumables",
        "name": "营销中心低值耗材",
        "detail_name_contains": ["低值耗材"],
    },
    {
        "code": "marketing_telephone_expense",
        "name": "营销中心电话费",
        "detail_name_contains": ["电话费"],
    },
    {
        "code": "marketing_intl_express_expense",
        "name": "营销中心国际快递费",
        # 只取国际（外贸快递）；内贸快递、快递费、运输费用另有维度，需要时再加
        "detail_name_contains": ["外贸快递"],
    },
    {
        "code": "marketing_domestic_express_expense",
        "name": "营销中心国内快递费",
        "detail_name_contains": ["内贸快递", "快递费"],
    },
    {
        "code": "marketing_welfare_expense",
        "name": "营销中心福利费",
        # 只取「其他福利」；奖金/补贴类（业绩提成奖金、年终奖金、岗位补贴等）不在本指标口径
        "detail_name_contains": ["其他福利"],
    },
    {
        "code": "marketing_utility_expense",
        "name": "营销中心水电费",
        # 水费/电费（「基础电费」也含"电费"，会一并计入；「电话费」不含"电费"子串，不会误纳）
        "detail_name_contains": ["水费", "电费"],
    },
    {
        "code": "marketing_platform_expense",
        "name": "营销中心平台费",
        # 按费用项目精确匹配（括号为全角，与 ERP 维度名称一致）
        "detail_name_contains": [
            "专用平台费用",
            "平台交易服务费",
            "平台费（非运营平台-公众号）",
            "平台固定费（年费/月租）",
            "平台延迟发货赔付费",
        ],
    },
    {
        "code": "marketing_after_sales_expense",
        "name": "营销中心售后费用",
        # 按 5 个售后费用项目精确匹配；注意「售后组/电话费」这类"部门名含售后"的行不会被计入
        "detail_name_contains": [
            "售后其它费用",
            "售后运输费",
            "售后赔偿费",
            "售后返工费",
        ],
    },
    {
        "code": "marketing_entertainment_expense",
        "name": "营销中心业务招待费",
        "detail_name_contains": ["业务招待费"],
    },
    {
        "code": "marketing_transport_expense",
        "name": "营销中心运输费",
        # 只取「运输费用」；「售后运输费」属售后费用指标口径，不在此指标内
        "detail_name_contains": ["运输费用"],
    },
    {
        "code": "marketing_recruitment_expense",
        "name": "营销中心招聘服务费",
        # ERP 维度名是「招聘费」（无"招聘服务费"这一写法）
        "detail_name_contains": ["招聘费"],
    },
    {
        "code": "marketing_consulting_expense",
        "name": "营销中心咨询服务费",
        "detail_name_contains": ["咨询服务费"],
    },
    {
        "code": "marketing_repair_expense",
        "name": "营销中心维修费",
        # 「维修费」是「车辆维修费」的子串：车辆维修费只算车辆费用，这里排除掉；
        # 「FWX辅/维修」6601 下暂无行，保留关键字待出现
        "detail_name_contains": ["维修费", "FWX辅/维修"],
        "detail_name_exclude": ["车辆维修费"],
    },
    {
        "code": "marketing_depreciation_expense",
        "name": "营销中心折旧费用",
        "detail_name_contains": ["折旧费用"],
    },
    {
        "code": "marketing_promotion_expense",
        "name": "营销中心推广费",
        "detail_name_contains": [
            "推广补单服务费",
            "推广外链充值",
            "推广展会费用",
            "推广运营费",
            "推广店铺直通车",
            "推广SEO工具费用",
            "推广物流单号费",
        ],
    },
    {
        "code": "marketing_rent_property_expense",
        "name": "营销中心租金及物业管理费",
        "detail_name_contains": ["场地租金", "物业管理费"],
    },
    {
        "code": "marketing_ecommerce_association_fee",
        "name": "营销中心网商协会费",
        # 6601 下协会/活动类费用项目：参赛活动费；网商协会费该科目下暂无行，保留关键字待出现
        "detail_name_contains": ["网商协会费", "参赛活动费"],
    },
    {
        "code": "marketing_it_service_expense",
        "name": "营销中心信息技术服务费",
        # 6601 下网络服务费；实际发生额多记在 6602 管理费用，按 6601 口径取数为 0
        "detail_name_contains": ["网络服务费"],
    },
    {
        "code": "marketing_ar_balance",
        "name": "营销中心应收余额",
        # 应收余额：科目 1122 应收账款，剔除组织 100-113 的内部客户，取期末余额（借方 - 贷方）
        "account_prefix": "1122",
        "formula": (
            "SUM(FENDDEBIT - FENDCREDIT) WHERE 科目=1122 应收账款 "
            "AND 客户编码 NOT IN (100,101,102,103,104,105,106,107,108,109,110,111,112,113)"
        ),
        "description": (
            "营销中心月度报表使用：所有组织、科目 1122 应收账款下外部客户（剔除编码 100-113 的内部客户）"
            "的期末余额（借方-贷方）；月指标，每日重算当月数值，每次计算保留 calc_version 版本。"
        ),
        "measures_extra": {
            "require_detail": True,
            "detail_is_department": False,
            "detail_code_exclude_in": [str(code) for code in range(100, 114)],
            "amount_terms": [
                {"field": "FENDDEBIT", "sign": 1},
                {"field": "FENDCREDIT", "sign": -1},
            ],
        },
    },
    {
        "code": "marketing_ap_balance",
        "name": "营销中心应付余额",
        # 应付余额：科目 2202 应付账款，剔除组织 100-113 的内部往来单位，取期末贷方余额（贷方 - 借方）
        "account_prefix": "2202",
        "formula": (
            "SUM(FENDCREDIT - FENDDEBIT) WHERE 科目=2202 应付账款 "
            "AND 往来单位编码 NOT IN (100,101,102,103,104,105,106,107,108,109,110,111,112,113)"
        ),
        "description": (
            "营销中心月度报表使用：所有组织、科目 2202 应付账款下外部往来单位（剔除编码 100-113 的内部组织）"
            "的期末贷方余额（贷方-借方）；月指标，每日重算当月数值，每次计算保留 calc_version 版本。"
        ),
        "measures_extra": {
            "require_detail": True,
            "detail_is_department": False,
            "detail_code_exclude_in": [str(code) for code in range(100, 114)],
            "amount_terms": [
                {"field": "FENDCREDIT", "sign": 1},
                {"field": "FENDDEBIT", "sign": -1},
            ],
        },
    },
    {
        "code": "marketing_total_expense",
        "name": "营销中心费用合计",
        # 汇总指标：值 = 下列组成指标当期组织合计之和（kind=metric_sum，自身不取数）
        "measures": {
            "kind": "metric_sum",
            "group_by_org": True,
            "component_metric_codes": [
                "marketing_office_expense",
                "marketing_travel_expense",
                "marketing_vehicle_expense",
                "marketing_low_value_consumables",
                "marketing_telephone_expense",
                "marketing_welfare_expense",
                "marketing_intl_express_expense",
                "marketing_domestic_express_expense",
                "marketing_platform_expense",
                "marketing_consulting_expense",
                "marketing_after_sales_expense",
                "marketing_utility_expense",
                "marketing_promotion_expense",
                "marketing_repair_expense",
                "marketing_entertainment_expense",
                "marketing_transport_expense",
                "marketing_recruitment_expense",
                "marketing_ecommerce_association_fee",
                "marketing_it_service_expense",
                "marketing_inventory_capital_cost",
            ],
        },
        "formula": "SUM(组成指标当期值)：办公费+差旅费+车辆费用+低值耗材+电话费+福利费+国际快递费+国内快递费+平台费+咨询服务费+售后费用+水电费+推广费+维修费+业务招待费+运输费+招聘服务费+网商协会费+信息技术服务费+库存资金占用费",
        "description": (
            "营销中心费用合计：上列 20 个费用/资金占用指标当期值之和（按组织分别合计，"
            "库存资金占用费为公司级指标、单列为组织为空的一行）；"
            "月指标每日重算当月值；组成指标口径变化后需重算本指标。"
        ),
    },
    {
        "code": "marketing_fixed_expense_subtotal",
        "name": "营销中心营销固定费用小计",
        # 汇总指标：值 = 折旧费用 + 租金及物业管理费（kind=metric_sum，自身不取数）
        "measures": {
            "kind": "metric_sum",
            "group_by_org": True,
            "component_metric_codes": [
                "marketing_depreciation_expense",
                "marketing_rent_property_expense",
            ],
        },
        "formula": "SUM(营销中心折旧费用 + 营销中心租金及物业管理费)",
        "description": (
            "营销中心营销固定费用小计 = 营销中心折旧费用 + 营销中心租金及物业管理费"
            "（按组织分别合计）；两者均取自科目 6601 销售费用下的费用项目，属固定费用口径；"
            "月指标每日重算当月值；组成指标口径变化后需重算本指标。"
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

        for item in METRIC_DEFS:
            keywords = item.get("detail_name_contains") or []
            if item.get("measures"):
                # 完整口径（如 metric_sum 汇总指标），不再叠加科目余额表基础配置
                measures = dict(item["measures"])
            else:
                measures = {**BASE_MEASURES}
                if item.get("account_prefix"):
                    measures["account_prefix"] = item["account_prefix"]
                if keywords:
                    measures["detail_name_contains"] = keywords
                if item.get("detail_name_exclude"):
                    measures["detail_name_exclude"] = item["detail_name_exclude"]
                measures.update(item.get("measures_extra") or {})

            account = str(measures.get("account_prefix") or "")
            if item.get("formula"):
                formula = str(item["formula"])
                scope_text = str(item.get("scope_text") or "")
            else:
                formula_condition = " AND ".join(f"核算维度名称 LIKE '%{word}%'" for word in keywords)
                if len(keywords) > 1:
                    formula_condition = f"({formula_condition})"
                for word in item.get("detail_name_exclude") or []:
                    formula_condition += f" AND 核算维度名称 NOT LIKE '%{word}%'"
                formula = f"SUM({measures.get('amount_field', 'FDEBIT')}) WHERE 科目={account} AND {formula_condition}"
                scope_text = "、".join(keywords)
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == item["code"]))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=item["code"])
                db.add(metric)
            metric.name = item["name"]
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.formula = formula
            metric.dimensions = DIMENSIONS
            metric.measures = measures
            metric.source_entity_id = None if item.get("measures") else entity.id
            metric.status = 0
            if item.get("description"):
                metric.description = str(item["description"])
            else:
                metric.description = (
                    f"营销中心月度报表使用：所有组织、科目 {account} 下核算维度名称含「{scope_text}」的"
                    "本期借方发生额汇总；月指标，每日重算当月累计值，每次计算保留 calc_version 版本。"
                )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
