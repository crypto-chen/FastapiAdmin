"""初始化营销中心库存类派生指标（不新增来源对象/同步任务）：

1. **营销中心备货订单库存** ``marketing_stockup_order_instock``
   = 海柔库存 + 机箱成品仓；
2. **营销中心库存合计（未税）** ``marketing_inventory_total_untaxed``
   = 外部订单库存（未税）+ 备货订单库存。

口径（用户给定）

- 海柔库存 `marketing_hairou_inventory` = CRM `/hs/getHaiRou` 返回的
  「按入库时间落在期间内的海柔在库库存金额」（口径见 `seed_crm_inventory_metrics.py`）；
- 机箱成品仓 `marketing_chassis_warehouse_balance` = 金蝶《存货收发存汇总表》中
  组织 100、仓库区间 `JXCPC~JXCPC` 的期末结存金额 `FENDAmount`
  （口径见 `seed_marketing_chassis_warehouse_metric.py`）；
- 外部订单库存（未税）`marketing_external_order_inventory_untaxed` = CRM `/hs/getNoChuHuo`
  返回的「完工齐套但未出货的订单金额」（口径见 `seed_crm_inventory_metrics.py`）。

两个指标都是取数类型 `kind = metric_sum`：直接合计组成指标**当期**的组织合计行
（引擎会在计算前按同一期间补齐缺结果的组成指标，缺结果时按 0 计入并告警）。

说明：该指标 code 沿用原先的 `marketing_stockup_order_instock`
（「营销中心备货订单库存」）。它此前挂过「生产入库」口径，该口径已迁移到
`marketing_stockup_prod_instock`（营销中心当期备货生产入库指标）；本脚本把它改写为
「海柔库存 + 机箱成品仓」。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

依赖：
- 海柔库存：``python scripts/seed_crm_inventory_metrics.py``
- 机箱成品仓：``python scripts/seed_marketing_chassis_warehouse_metric.py``
- 外部订单库存（未税）：``python scripts/seed_crm_inventory_metrics.py``

用法：
    python scripts/seed_marketing_stockup_inventory_metric.py
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

METRIC_CODE = "marketing_stockup_order_instock"
METRIC_NAME = "营销中心备货订单库存"
DIMENSIONS = {"org": False, "dept": False}

# 一个指标一条：kind = metric_sum，component_metric_codes 是组成指标编码
METRICS = [
    {
        "code": METRIC_CODE,
        "name": METRIC_NAME,
        "component_codes": [
            "marketing_hairou_inventory",
            "marketing_chassis_warehouse_balance",
        ],
        "description": (
            "营销中心备货订单库存 = 海柔库存 + 机箱成品仓："
            "① 海柔库存（marketing_hairou_inventory）= CRM /hs/getHaiRou 按入库时间落在期间内的"
            "海柔在库库存金额（数量 qtyTotal × 单位成本[加工成本+材料成本]，取值路径 data.data）；"
            "② 机箱成品仓（marketing_chassis_warehouse_balance）= 金蝶《存货收发存汇总表》组织 100、"
            "仓库区间 JXCPC~JXCPC 的期末结存金额 FENDAmount。"
            "合计口径为公司整体（不按组织/部门拆分），组成指标缺当期结果时由引擎先补齐，"
            "仍缺则按 0 计入并告警。月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，"
            "每次计算保留 calc_version 版本。"
        ),
    },
    {
        "code": "marketing_inventory_total_untaxed",
        "name": "营销中心库存合计（未税）",
        "component_codes": [
            "marketing_external_order_inventory_untaxed",
            METRIC_CODE,
        ],
        "description": (
            "营销中心库存合计（未税）= 外部订单库存（未税）+ 备货订单库存："
            "① 外部订单库存（未税）（marketing_external_order_inventory_untaxed）"
            "= CRM /hs/getNoChuHuo 完工齐套但未出货的订单金额，按订单创建时间落在期间内、"
            "为时点快照（历史月份会被后来的出货改写）；"
            "② 备货订单库存（marketing_stockup_order_instock）= 海柔库存 + 机箱成品仓"
            "（按入库时间的海柔在库库存金额 + 金蝶机箱成品仓期末结存金额）。"
            "合计口径为公司整体（不按组织/部门拆分），组成指标缺当期结果时由引擎先补齐，"
            "仍缺则按 0 计入并告警。月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，"
            "每次计算保留 calc_version 版本。"
        ),
    },
    {
        "code": "marketing_inventory_avg_untaxed",
        "name": "营销中心平均库存（未税）",
        "component_codes": ["marketing_inventory_total_untaxed"],
        "kind": "metric_balance_avg",
        "description": (
            "营销中心平均库存（未税）=（期初 + 期末）÷ 2："
            "期末取当期「营销中心库存合计（未税）」（marketing_inventory_total_untaxed = "
            "外部订单库存 + 海柔库存 + 机箱成品仓）结果，期初取**上一期**同指标结果"
            "（月指标即上月末），两者各取 0.5 后相加（kind=metric_balance_avg，"
            "begin_weight/end_weight 可调）；上一期无结果时按 0 计入并告警"
            "（如 2026-01 的期初为 2025-12，若该期取不到数则等于当期的一半）。"
            "公司整体口径，计算前由引擎先补齐当期与上一期的组成指标结果。"
            "月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，"
            "每次计算保留 calc_version 版本。"
        ),
    },
    {
        "code": "marketing_inventory_capital_cost",
        "name": "营销中心库存资金占用费",
        "component_codes": ["marketing_inventory_avg_untaxed"],
        "kind": "metric_scale",
        "scale": 0.01,
        "description": (
            "营销中心库存资金占用费 = 营销中心平均库存（未税）× 1%："
            "组成指标 marketing_inventory_avg_untaxed（=（期初 + 期末）÷ 2 的「营销中心库存合计（未税）」），"
            "取数类型 kind=metric_scale（值为「组成指标当期值之和 × scale 系数」，scale=0.01 即 1%）。"
            "公司整体口径，组成指标缺当期结果时由引擎先补齐，仍缺则按 0 计入并告警。"
            "月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，每次计算保留 calc_version 版本。"
        ),
    },
    {
        "code": "marketing_inventory_turnover_days",
        "name": "营销中心库存周转天数",
        "kind": "metric_ratio",
        "numerator_codes": ["marketing_inventory_avg_untaxed"],
        "denominator_codes": ["marketing_sales_cost"],
        "ratio_scale": 30,
        "description": (
            "营销中心库存周转天数 = 营销中心平均库存（未税）÷ 当期销售成本 × 30（天）："
            "分子 marketing_inventory_avg_untaxed（=（期初 + 期末）÷ 2 的「营销中心库存合计（未税）」），"
            "分母 marketing_sales_cost（营销中心销售成本 = 组织 100 科目 6401 主营业务成本"
            "本期借方发生额，口径见 seed_marketing_sales_cost_metric.py）；"
            "取数类型 kind=metric_ratio（分子合计 ÷ 分母合计 × ratio_scale，ratio_scale=30 输出天数，"
            "分母为 0 时取 0）。公司整体口径，组成指标缺当期结果时由引擎先补齐，"
            "仍缺则按 0 计入并告警。月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，"
            "每次计算保留 calc_version 版本。"
        ),
    },
    {
        "code": "marketing_inventory_to_order_ratio",
        "name": "库存与接单比",
        "kind": "metric_ratio",
        "numerator_codes": ["marketing_inventory_total_untaxed"],
        "denominator_codes": ["marketing_order_intake_untaxed"],
        "ratio_scale": 1,
        "description": (
            "库存与接单比 = 营销中心库存合计（未税）÷ 营销中心接单金额（未税）："
            "分子 marketing_inventory_total_untaxed（= 外部订单库存 + 海柔库存 + 机箱成品仓，"
            "期时点口径），分母 marketing_order_intake_untaxed"
            "（= 零售/批量/打样/备货订单（未税）+ 设计费收入（未税），见 seed_crm_marketing_metrics.py）；"
            "取数类型 kind=metric_ratio，ratio_scale=1 输出**倍数**（如 0.87 表示库存相当于当月接单的 0.87 倍；"
            "若要看百分数，把 ratio_scale 改成 100 即可），分母为 0 时取 0。"
            "公司整体口径，组成指标缺当期结果时由引擎先补齐，仍缺则按 0 计入并告警。"
            "月指标，每日 02:30 重算当月，次月 1 日重拉上月并重算，每次计算保留 calc_version 版本。"
        ),
    },
]


async def main() -> None:
    async with async_db_session() as db, db.begin():
        for spec in METRICS:
            kind = spec.get("kind", "metric_sum")
            # 比率指标用分子/分母两组编码，其余用一组组成指标
            numerator_codes = list(spec.get("numerator_codes") or [])
            denominator_codes = list(spec.get("denominator_codes") or [])
            component_codes = list(spec.get("component_codes") or [])
            check_codes = numerator_codes + denominator_codes + component_codes
            missing: list[str] = []
            for code in check_codes:
                exists = (
                    await db.execute(select(MetricDefModel.id).where(MetricDefModel.code == code))
                ).scalars().first()
                if exists is None:
                    missing.append(code)
            if missing:
                raise SystemExit(f"缺少组成指标 {missing}，请先执行对应 seed 脚本")

            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == spec["code"]))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=spec["code"])
                db.add(metric)
            metric.name = spec["name"]
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.dimensions = DIMENSIONS
            # 一个指标一条：按 kind 组装 measures 与公式
            measures: dict = {"kind": kind}
            if kind == "metric_ratio":
                # 分子 ÷ 分母 × ratio_scale（如库存周转天数 = 平均库存 ÷ 销售成本 × 30）
                ratio_scale = float(spec.get("ratio_scale", 1))
                measures.update(
                    {
                        "numerator_metric_codes": numerator_codes,
                        "denominator_metric_codes": denominator_codes,
                        "ratio_scale": ratio_scale,
                    }
                )
                formula = f"（{' + '.join(numerator_codes)}）÷（{' + '.join(denominator_codes)}）"
                if ratio_scale != 1:
                    formula += f" × {ratio_scale:g}"
                metric.formula = formula
            elif kind == "metric_balance_avg":
                # （期初 + 期末）÷ 2
                measures["component_metric_codes"] = component_codes
                measures.update({"begin_weight": 0.5, "end_weight": 0.5})
                metric.formula = (
                    "（上期 " + " + ".join(component_codes) + " × 0.5）"
                    "+（当期 " + " + ".join(component_codes) + " × 0.5）"
                )
            elif kind == "metric_scale":
                # 组成指标当期值 × scale（如资金占用费 = 平均库存 × 1%）
                measures["component_metric_codes"] = component_codes
                scale = float(spec.get("scale", 1))
                measures["scale"] = scale
                metric.formula = f"（{' + '.join(component_codes)}）× {scale * 100:g}%"
            else:
                measures["component_metric_codes"] = component_codes
                metric.formula = " + ".join(component_codes)
            metric.measures = measures
            metric.source_entity_id = None  # 派生指标自身不取数
            metric.status = 0
            metric.description = spec["description"]
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")
            print(f"    组成指标: {' + '.join(check_codes)} | kind={kind}")

    await async_engine.dispose()
    print("营销中心库存类派生指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
