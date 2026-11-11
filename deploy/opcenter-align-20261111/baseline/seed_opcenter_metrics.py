"""初始化运营中心主表指标（科目 6601 销售费用 + 部门过滤）。

口径：所有组织、科目 6601（销售费用）、核算维度「部门/费用项目」中
部门属于「在线营销部、社媒组、电商组、官网」、且费用项目名称含指定关键字的
本期借方发生额（FDEBITLOCAL）汇总。月指标，每日重算当月累计值。

与营销中心主表指标同源同关键字，仅多一层部门过滤；营销中心不限制部门，
因此同一费用项目在两套指标下会得到不同小计，属预期差异。

用法：
    python scripts/seed_opcenter_metrics.py
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

CATEGORY = "运营中心-主表指标"
DEPARTMENTS = ["在线营销部", "社媒组", "电商组", "官网"]

# 取数规则：由指标计算引擎解释，改口径只改这里。
BASE_MEASURES = {
    "kind": "account_balance_filter",
    "source_object_code": "GL_RPT_AccountBalance",
    "account_field": "FBALANCEID",
    "account_prefix": "6601",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    # 科目余额表按「综合本位币」(FCURRENCY=0) 取数：原币列为空，金额取本位币列
    "amount_field": "FDEBITLOCAL",
    # 核算维度为「部门/费用项目」，只保留指定部门
    "department_names": DEPARTMENTS,
}
DIMENSIONS = {"org": True, "dept": True}

METRIC_DEFS = [
    {"code": "OPC-COST-01", "name": "运营中心办公费", "detail_name_contains": ["办公费"]},
    {
        "code": "OPC-COST-02",
        "name": "运营中心差旅费",
        "detail_name_contains": ["差旅费", "交通差旅"],
    },
    {
        "code": "OPC-COST-03",
        "name": "运营中心车辆费用",
        "detail_name_contains": [
            "过路费",
            "车辆维修费",
            "车辆年审保养保险",
            "车油卡充值",
            "停车费",
            "交通费",
        ],
    },
    {"code": "OPC-COST-04", "name": "运营中心低值耗材", "detail_name_contains": ["低值耗材"]},
    {"code": "OPC-COST-05", "name": "运营中心电话费", "detail_name_contains": ["电话费"]},
    {
        "code": "OPC-COST-06",
        "name": "运营中心福利费",
        "detail_name_contains": ["其他福利", "直接人工-其他福利"],
    },
    {
        "code": "OPC-COST-07",
        "name": "运营中心国际快递费",
        "detail_name_contains": ["外贸快递", "报关费"],
    },
    {
        "code": "OPC-COST-08",
        "name": "运营中心国内快递费",
        "detail_name_contains": ["内贸快递", "售后运输费"],
        # 与营销中心一致：2026-10 售后运输费重分类到售后费用
        "detail_name_contains_by_period": {"2026-10": ["内贸快递"]},
    },
    {
        "code": "OPC-COST-09",
        "name": "运营中心平台费",
        "detail_name_contains": [
            "专用平台费用",
            "平台交易服务费",
            "平台费（非运营平台-公众号）",
            "平台延迟发货赔付费",
            "平台固定费",
        ],
    },
    {
        "code": "OPC-COST-10",
        "name": "运营中心售后费用",
        "detail_name_contains": ["售后其它费用", "售后赔偿费", "售后返工费"],
        "detail_name_contains_by_period": {
            "2026-10": ["售后其它费用", "售后赔偿费", "售后返工费", "售后运输费"],
        },
    },
    {"code": "OPC-COST-11", "name": "运营中心水电费", "detail_name_contains": ["水费", "电费"]},
    {
        "code": "OPC-COST-12",
        "name": "运营中心推广费",
        "detail_name_contains": [
            "推广补单服务费",
            "推广外链充值",
            "推广展会费用",
            "推广运营费",
            "推广店铺直通车",
            "推广SEO工具费用",
            "推广物流单号费",
            "商务费用",
        ],
    },
    {
        "code": "OPC-COST-13",
        "name": "运营中心维修费",
        "detail_name_contains": ["维修费", "FWX辅/维修"],
        # 「维修费」是「车辆维修费」的子串，车辆维修费只算车辆费用
        "detail_name_exclude": ["车辆维修费"],
    },
    {
        "code": "OPC-COST-14",
        "name": "运营中心业务招待费",
        "detail_name_contains": ["业务招待费"],
    },
    {
        "code": "OPC-COST-15",
        "name": "运营中心运输费",
        "detail_name_contains": ["运输费用", "快递费"],
    },
    {"code": "OPC-COST-16", "name": "运营中心招聘服务费", "detail_name_contains": ["招聘费"]},
    {
        "code": "OPC-COST-17",
        "name": "运营中心咨询服务费",
        "detail_name_contains": ["咨询服务费"],
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
            keywords = item["detail_name_contains"]
            measures = {**BASE_MEASURES}
            measures["detail_name_contains"] = keywords
            if item.get("detail_name_contains_by_period"):
                measures["detail_name_contains_by_period"] = item["detail_name_contains_by_period"]
            if item.get("detail_name_exclude"):
                measures["detail_name_exclude"] = item["detail_name_exclude"]

            formula_condition = " OR ".join(f"核算维度名称 LIKE '%{word}%'" for word in keywords)
            if len(keywords) > 1:
                formula_condition = f"({formula_condition})"
            for word in item.get("detail_name_exclude") or []:
                formula_condition += f" AND 核算维度名称 NOT LIKE '%{word}%'"
            dept_condition = "、".join(f"'{name}'" for name in DEPARTMENTS)
            formula = (
                f"SUM({measures['amount_field']}) WHERE 科目=6601 "
                f"AND 部门 IN ({dept_condition}) AND {formula_condition}"
            )
            period_overrides = item.get("detail_name_contains_by_period") or {}
            if period_overrides:
                override_text = "；".join(
                    f"{period} 改为 {' OR '.join(words)}" for period, words in period_overrides.items()
                )
                formula = f"{formula}；期间覆盖：{override_text}"

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
            metric.formula = formula
            metric.dimensions = DIMENSIONS
            metric.measures = measures
            metric.source_entity_id = entity.id
            metric.status = 0
            metric.description = (
                f"运营中心月度报表使用：所有组织、科目 6601 下核算维度部门属于"
                f"「{'、'.join(DEPARTMENTS)}」且名称含「{'、'.join(keywords)}」的本期借方发生额汇总；"
                "月指标，每日重算当月累计值，每次计算保留 calc_version 版本。"
            )
            if period_overrides:
                metric.description = f"{metric.description.rstrip('。')}；期间覆盖：{override_text}。"
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
