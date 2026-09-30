"""初始化营销中心「总部分摊（PER-02）」系列指标（全部为派生指标，不调外部接口）。

口径依据：集团总部分摊规则表（PER-02 系列）。全部以 **REV-01 = 营销中心对外出货未税销售额（净额）**
（指标编码 ``marketing_external_shipment_net_untaxed``）为基数按固定比例分摊，
**只做分摊列示、不是实际发生额**：

===========================  =============  ==========  =================================
业务编码                      指标           固定/变动    计算式
===========================  =============  ==========  =================================
PER-02                       总部分摊合计     固定/变动    PER-02-a + PER-02-b + PER-02-c（= REV-01 × 2.00%）
PER-02-a                     HR 分摊         固定/变动    PER-02-a-1 + PER-02-a-2（= REV-01 × 0.80%）
PER-02-a-1                   -HR 变动        变动        REV-01 × 0.40%
PER-02-a-2                   -HR 固定        固定        REV-01 × 0.40%
PER-02-b                     财经分摊         固定/变动    PER-02-b-1 + PER-02-b-2（= REV-01 × 0.64%）
PER-02-b-1                   -财经变动        变动        REV-01 × 0.32%
PER-02-b-2                   -财经固定        固定        REV-01 × 0.32%
PER-02-c                     AI 数智化分摊     固定/变动    PER-02-c-1 + PER-02-c-2（= REV-01 × 0.56%）
PER-02-c-1                   -AI 数智化变动    变动        REV-01 × 0.28%
PER-02-c-2                   -AI 数智化固定    固定        REV-01 × 0.28%
===========================  =============  ==========  =================================

折算系数用小数表示百分比（0.40% → ``scale = 0.004``）。父级用 ``kind = metric_sum``
合计子项（与表里「= 子项相加」的公式一致），所以分组值只会随子项变化，不会出现两份口径漂移。

REV-01 不在本脚本里，属出货系列（``backend/scripts/seed_crm_shipment_metrics.py``）：
对外出货未税销售额（净额）= 货物出货（未税）+ 设计服务收入（未税）+ 退货/退款（负数）。
因此**要先有 REV-01 当期结果**（计算引擎会自动按期间补齐组成指标），
再算本系列；本脚本自身不建来源对象、不建同步任务。

另含两个**跨系列**汇总指标（公司整体口径，不按组织拆分，因为 PER-02 三项没有组织维度）：

- 「营销中心固定费用合计」= 营销固定费用小计（``marketing_fixed_expense_subtotal``，
  科目余额表口径，定义在 ``backend/scripts/seed_marketing_metrics.py``）
  + PER-02 的 HR 固定 + 财经固定 + AI 数智化固定。
- 「营销中心变动费用合计」= 营销中心费用合计（``marketing_total_expense``，科目余额表 6601 口径）
  + PER-02 的 HR 变动 + 财经变动 + AI 数智化变动。
- 「营销中心边际贡献」= 总收益（营销结算收入）（``marketing_total_income_settlement``，
  REV-01 × 10%）− 变动费用合计（``metric_diff`` 取数类型）。
- 「营销中心边际贡献率」= 边际贡献 ÷ 总收益（营销结算收入）× 100%
  （``metric_ratio`` 取数类型，``ratio_scale = 100`` 输出百分数）。
- 「营销中心结算收益」= 边际贡献 − 固定费用合计（``metric_diff`` 取数类型）。
- 「营销中心结算收益率」= 结算收益 ÷ 对外出货未税销售额（净额）REV-01 × 100%
  （``metric_ratio`` 取数类型，``ratio_scale = 100`` 输出百分数）。
- 「营销中心盈亏平衡点销售额」= 固定费用合计 ÷ 边际贡献率
  （``metric_ratio`` 取数类型；边际贡献率按百分数存储，故 ``ratio_scale = 100`` 还原小数口径）。
- 「营销中心安全边际率」=（总收益（营销结算收入）− 盈亏平衡点销售额）÷ 总收益（营销结算收入）× 100%
  （``metric_ratio`` 取数类型，分子用 ``numerator_subtrahend_metric_codes`` 声明减项）。
- 「营销中心单位时间附加值」= 结算收益 ÷ 总劳动时间
  （``metric_ratio`` 取数类型，``ratio_scale = 1``，单位显式声明为「元/小时」）。
- 「营销中心变动费用率（不含人工）」= 变动费用合计 ÷ 对外出货未税销售额（净额）REV-01 × 100%
  （``metric_ratio`` 取数类型，``ratio_scale = 100`` 输出百分数）。
- 「营销中心固定费用率（不含人工）」= 固定费用合计 ÷ 对外出货未税销售额（净额）REV-01 × 100%
  （``metric_ratio`` 取数类型，``ratio_scale = 100`` 输出百分数）。
- 「营销中心成本费用率（不含人工）」=（营销中心费用合计 + 营销固定费用小计 + 总部分摊合计）
  ÷ 对外出货未税销售额（净额）REV-01 × 100%（``metric_ratio`` 取数类型，分子为三项指标之和；
  与「固定费用率 + 变动费用率」恒等，可用于交叉校验）。
- 「营销中心库存资金占用率」= 库存资金占用费 ÷ 对外出货未税销售额（净额）REV-01 × 100%
  （``metric_ratio`` 取数类型，``ratio_scale = 100`` 输出百分数）。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_marketing_allocation_metrics.py
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
from app.modules.metadata.model import SourceSystemModel  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

# 与订单/出货/下推系列共用同一个 CRM 连接与来源系统（本脚本不新增接口，仅保持来源一致）
CONNECTION_NAME = "CRM 默认连接"
SOURCE_SYSTEM_CODE = "crm"

# REV-01：对外出货未税销售额（净额），由出货系列维护
REV01_CODE = "marketing_external_shipment_net_untaxed"
DIMENSIONS = {"org": False, "dept": False}

# 一个指标一条；``amount_rule`` 只用于拼说明文案
PCT_RULE = "按集团分摊规则、以对外出货未税净额（REV-01）为基数折算，仅分摊列示、非实际发生额。"

METRICS = [
    {
        "code": "marketing_per02_hr_variable",
        "name": "营销中心HR变动（PER-02-a-1）",
        "kind": "metric_scale",
        "component_metric_codes": [REV01_CODE],
        "scale": 0.004,
        "rule": "【PER-02-a-1 HR变动｜变动】对外出货未税净额 REV-01 × 0.40%。",
    },
    {
        "code": "marketing_per02_hr_fixed",
        "name": "营销中心HR固定（PER-02-a-2）",
        "kind": "metric_scale",
        "component_metric_codes": [REV01_CODE],
        "scale": 0.004,
        "rule": "【PER-02-a-2 HR固定｜固定】对外出货未税净额 REV-01 × 0.40%。",
    },
    {
        "code": "marketing_per02_hr_allocation",
        "name": "营销中心HR分摊（PER-02-a）",
        "kind": "metric_sum",
        "component_metric_codes": ["marketing_per02_hr_variable", "marketing_per02_hr_fixed"],
        "rule": "【PER-02-a HR分摊｜固定/变动】= PER-02-a-1 + PER-02-a-2（等价于 REV-01 × 0.80%）。",
    },
    {
        "code": "marketing_per02_finance_variable",
        "name": "营销中心财经变动（PER-02-b-1）",
        "kind": "metric_scale",
        "component_metric_codes": [REV01_CODE],
        "scale": 0.0032,
        "rule": "【PER-02-b-1 财经变动｜变动】对外出货未税净额 REV-01 × 0.32%。",
    },
    {
        "code": "marketing_per02_finance_fixed",
        "name": "营销中心财经固定（PER-02-b-2）",
        "kind": "metric_scale",
        "component_metric_codes": [REV01_CODE],
        "scale": 0.0032,
        "rule": "【PER-02-b-2 财经固定｜固定】对外出货未税净额 REV-01 × 0.32%。",
    },
    {
        "code": "marketing_per02_finance_allocation",
        "name": "营销中心财经分摊（PER-02-b）",
        "kind": "metric_sum",
        "component_metric_codes": [
            "marketing_per02_finance_variable",
            "marketing_per02_finance_fixed",
        ],
        "rule": "【PER-02-b 财经分摊｜固定/变动】= PER-02-b-1 + PER-02-b-2（等价于 REV-01 × 0.64%）。",
    },
    {
        "code": "marketing_per02_ai_variable",
        "name": "营销中心AI数智化变动（PER-02-c-1）",
        "kind": "metric_scale",
        "component_metric_codes": [REV01_CODE],
        "scale": 0.0028,
        "rule": "【PER-02-c-1 AI数智化变动｜变动】对外出货未税净额 REV-01 × 0.28%。",
    },
    {
        "code": "marketing_per02_ai_fixed",
        "name": "营销中心AI数智化固定（PER-02-c-2）",
        "kind": "metric_scale",
        "component_metric_codes": [REV01_CODE],
        "scale": 0.0028,
        "rule": "【PER-02-c-2 AI数智化固定｜固定】对外出货未税净额 REV-01 × 0.28%。",
    },
    {
        "code": "marketing_per02_ai_allocation",
        "name": "营销中心AI数智化分摊（PER-02-c）",
        "kind": "metric_sum",
        "component_metric_codes": ["marketing_per02_ai_variable", "marketing_per02_ai_fixed"],
        "rule": "【PER-02-c AI数智化分摊｜固定/变动】= PER-02-c-1 + PER-02-c-2（等价于 REV-01 × 0.56%）。",
    },
    {
        # 父级用「子项相加」，与规则表里 PER-02 = PER-02-a + PER-02-b + PER-02-c 一致
        "code": "marketing_per02_total",
        "name": "营销中心总部分摊合计（PER-02）",
        "kind": "metric_sum",
        "component_metric_codes": [
            "marketing_per02_hr_allocation",
            "marketing_per02_finance_allocation",
            "marketing_per02_ai_allocation",
        ],
        "rule": "【PER-02 总部分摊合计｜固定/变动】= PER-02-a + PER-02-b + PER-02-c"
        "（等价于 REV-01 × 2.00%）。",
    },
    {
        # 跨系列汇总：科目余额表口径的固定费用小计 + 三项 PER-02 固定分摊
        "code": "marketing_fixed_expense_total",
        "name": "营销中心固定费用合计",
        "kind": "metric_sum",
        "component_metric_codes": [
            "marketing_fixed_expense_subtotal",
            "marketing_per02_hr_fixed",
            "marketing_per02_finance_fixed",
            "marketing_per02_ai_fixed",
        ],
        "rule": "固定费用合计 = 营销固定费用小计（折旧费用 + 租金及物业管理费）+ HR 固定（PER-02-a-2）"
        "+ 财经固定（PER-02-b-2）+ AI 数智化固定（PER-02-c-2）；"
        "前三项来自科目余额表实际发生额口径，后三项为对外出货未税净额的分摊列示值。",
    },
    {
        # 跨系列汇总：科目余额表口径的营销中心费用合计 + 三项 PER-02 变动分摊
        "code": "marketing_variable_expense_total",
        "name": "营销中心变动费用合计",
        "kind": "metric_sum",
        "component_metric_codes": [
            "marketing_total_expense",
            "marketing_per02_hr_variable",
            "marketing_per02_finance_variable",
            "marketing_per02_ai_variable",
        ],
        "rule": "变动费用合计 = 营销中心费用合计 + HR 变动（PER-02-a-1）+ 财经变动（PER-02-b-1）"
        "+ AI 数智化变动（PER-02-c-1）；"
        "第一项来自科目余额表实际发生额口径（含公司级库存资金占用费），后三项为对外出货未税净额的分摊列示值。",
    },
    {
        # 跨系列汇总：边际贡献 = 总收益（营销结算收入）− 变动费用合计
        "code": "marketing_contribution_margin",
        "name": "营销中心边际贡献",
        "kind": "metric_diff",
        "addend_metric_codes": ["marketing_total_income_settlement"],
        "subtrahend_metric_codes": ["marketing_variable_expense_total"],
        "rule": "边际贡献 = 总收益（营销结算收入）− 变动费用合计；"
        "总收益 = 对外出货未税净额 REV-01 × 10%（营销结算收入，分摊列示口径），"
        "变动费用合计 = 营销中心费用合计 + HR 变动（PER-02-a-1）+ 财经变动（PER-02-b-1）"
        "+ AI 数智化变动（PER-02-c-1）。",
    },
    {
        # 比率：边际贡献率 = 边际贡献 ÷ 总收益（营销结算收入）× 100%
        "code": "marketing_contribution_margin_rate",
        "name": "营销中心边际贡献率",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_contribution_margin"],
        "denominator_metric_codes": ["marketing_total_income_settlement"],
        "ratio_scale": 100,
        "rule": "边际贡献率 = 边际贡献 ÷ 总收益（营销结算收入）× 100%（百分数）；"
        "分子为「营销中心边际贡献」（= 总收益 − 变动费用合计），分母为总收益（营销结算收入，"
        "对外出货未税净额 REV-01 × 10%）；分母为 0 时取 0。",
    },
    {
        # 差额：结算收益 = 边际贡献 − 固定费用合计
        "code": "marketing_settlement_income",
        "name": "营销中心结算收益",
        "kind": "metric_diff",
        "addend_metric_codes": ["marketing_contribution_margin"],
        "subtrahend_metric_codes": ["marketing_fixed_expense_total"],
        "rule": "结算收益 = 边际贡献 − 固定费用合计；"
        "边际贡献 = 总收益（营销结算收入）− 变动费用合计，"
        "固定费用合计 = 营销固定费用小计（折旧费用 + 租金及物业管理费）+ HR 固定（PER-02-a-2）"
        "+ 财经固定（PER-02-b-2）+ AI 数智化固定（PER-02-c-2）。",
    },
    {
        # 比率：结算收益率 = 结算收益 ÷ 对外出货未税销售额（净额）× 100%
        "code": "marketing_settlement_income_rate",
        "name": "营销中心结算收益率",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_settlement_income"],
        "denominator_metric_codes": [REV01_CODE],
        "ratio_scale": 100,
        "rule": "结算收益率 = 结算收益 ÷ 对外出货未税销售额（净额）× 100%（百分数）；"
        "分子为「营销中心结算收益」（= 边际贡献 − 固定费用合计），"
        "分母为对外出货未税销售额（净额）REV-01；分母为 0 时取 0。",
    },
    {
        # 比率：盈亏平衡点销售额 = 固定费用合计 ÷ 边际贡献率（率按百分数存储，故 ratio_scale = 100）
        "code": "marketing_break_even_sales",
        "name": "营销中心盈亏平衡点销售额",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_fixed_expense_total"],
        "denominator_metric_codes": ["marketing_contribution_margin_rate"],
        "ratio_scale": 100,
        # 结果是金额（元），不是比率：必须显式声明 unit，否则会按 ratio_scale=100 判成「%」
        "unit": "元",
        "rule": "盈亏平衡点销售额 = 固定费用合计 ÷ 边际贡献率；"
        "分子为「营销中心固定费用合计」（= 营销固定费用小计 + HR 固定 + 财经固定 + AI 数智化固定），"
        "分母为「营销中心边际贡献率」（百分数，如 37.8089 表示 37.8089%）；"
        "因分母按百分数存储，计算时再 × 100 还原为小数口径；分母为 0 时取 0"
        "（边际贡献率为负的月份会得到负值，表示当月不存在盈亏平衡点，请结合当月数据判断）。",
    },
    {
        # 比率：安全边际率 =（总收益（营销结算收入）− 盈亏平衡点销售额）÷ 总收益（营销结算收入）× 100%
        "code": "marketing_margin_of_safety_rate",
        "name": "营销中心安全边际率",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_total_income_settlement"],
        "numerator_subtrahend_metric_codes": ["marketing_break_even_sales"],
        "denominator_metric_codes": ["marketing_total_income_settlement"],
        "ratio_scale": 100,
        "rule": "安全边际率 =（总收益（营销结算收入）− 盈亏平衡点销售额）÷ 总收益（营销结算收入）× 100%"
        "（百分数）；分子为「总收益（营销结算收入）− 盈亏平衡点销售额」（即安全边际额），"
        "分母为总收益（营销结算收入，对外出货未税净额 REV-01 × 10%）；分母为 0 时取 0。",
    },
    {
        # 比率：单位时间附加值 = 结算收益 ÷ 总劳动时间（元/小时）
        "code": "marketing_value_added_per_hour",
        "name": "营销中心单位时间附加值",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_settlement_income"],
        "denominator_metric_codes": ["marketing_total_labor_hours"],
        "ratio_scale": 1,
        # 结果是「元/小时」，不是百分数：必须显式声明 unit，否则会退回默认单位「元」
        "unit": "元/小时",
        "rule": "单位时间附加值 = 结算收益 ÷ 总劳动时间（元/小时）；"
        "分子为「营销中心结算收益」（= 边际贡献 − 固定费用合计），"
        "分母为「营销中心总劳动时间」（= 正常工作时间 + 加班时间，来自 CRM 企微打卡）；"
        "分母为 0 时取 0（2026-01 ~ 2026-03 该接口无打卡数据、工时为 0，指标值同样为 0，不是真实人效）。",
    },
    {
        # 比率：变动费用率（不含人工）= 变动费用合计 ÷ 对外出货未税销售额（净额）× 100%
        "code": "marketing_variable_expense_rate",
        "name": "营销中心变动费用率（不含人工）",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_variable_expense_total"],
        "denominator_metric_codes": [REV01_CODE],
        "ratio_scale": 100,
        "rule": "变动费用率（不含人工）= 变动费用合计 ÷ 对外出货未税销售额（净额）× 100%（百分数）；"
        "分子为「营销中心变动费用合计」（= 营销中心费用合计 + HR 变动 + 财经变动 + AI 数智化变动），"
        "分母为对外出货未税销售额（净额）REV-01；分母为 0 时取 0。"
        "「不含人工」指分子取自科目 6601 费用项目口径：该口径下没有工资/社保类费用项目"
        "（仅含福利费、招聘服务费），不含营销中心人员薪酬。",
    },
    {
        # 比率：固定费用率（不含人工）= 固定费用合计 ÷ 对外出货未税销售额（净额）× 100%
        "code": "marketing_fixed_expense_rate",
        "name": "营销中心固定费用率（不含人工）",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_fixed_expense_total"],
        "denominator_metric_codes": [REV01_CODE],
        "ratio_scale": 100,
        "rule": "固定费用率（不含人工）= 固定费用合计 ÷ 对外出货未税销售额（净额）× 100%（百分数）；"
        "分子为「营销中心固定费用合计」（= 营销固定费用小计（折旧费用 + 租金及物业管理费）"
        "+ HR 固定 + 财经固定 + AI 数智化固定），分母为对外出货未税销售额（净额）REV-01；"
        "分母为 0 时取 0。"
        "「不含人工」指分子中的营销固定费用小计取自科目 6601 费用项目口径：该口径下没有工资/社保类"
        "费用项目，不含营销中心人员薪酬（PER-02 的 HR 固定属集团分摊列示值，仍计入分子）。",
    },
    {
        # 比率：成本费用率（不含人工）=（营销中心费用合计 + 营销固定费用小计 + 总部分摊合计）÷ REV-01 × 100%
        "code": "marketing_cost_expense_rate",
        "name": "营销中心成本费用率（不含人工）",
        "kind": "metric_ratio",
        "numerator_metric_codes": [
            "marketing_total_expense",
            "marketing_fixed_expense_subtotal",
            "marketing_per02_total",
        ],
        "denominator_metric_codes": [REV01_CODE],
        "ratio_scale": 100,
        "rule": "成本费用率（不含人工）=（营销中心费用合计 + 营销固定费用小计 + 总部分摊合计）"
        "÷ 对外出货未税销售额（净额）× 100%（百分数）；"
        "分子三项分别为 marketing_total_expense（科目 6601 费用合计，含公司级库存资金占用费）、"
        "marketing_fixed_expense_subtotal（折旧费用 + 租金及物业管理费）、"
        "marketing_per02_total（PER-02 总部分摊合计 = HR 0.80% + 财经 0.64% + AI 数智化 0.56%）；"
        "分母为对外出货未税销售额（净额）REV-01；分母为 0 时取 0。"
        "恒等式说明：本指标 ≡ 固定费用率（不含人工）+ 变动费用率（不含人工），"
        "两项相加可用于交叉校验。",
    },
    {
        # 比率：库存资金占用率 = 库存资金占用费 ÷ 对外出货未税销售额（净额）× 100%
        "code": "marketing_inventory_capital_cost_rate",
        "name": "营销中心库存资金占用率",
        "kind": "metric_ratio",
        "numerator_metric_codes": ["marketing_inventory_capital_cost"],
        "denominator_metric_codes": [REV01_CODE],
        "ratio_scale": 100,
        "rule": "库存资金占用率 = 库存资金占用费 ÷ 对外出货未税销售额（净额）× 100%（百分数）；"
        "分子为「营销中心库存资金占用费」（= 营销中心平均库存（未税）× 1%，"
        "平均库存 =（期初 + 期末）÷ 2 的「营销中心库存合计（未税）」，公司整体口径），"
        "分母为对外出货未税销售额（净额）REV-01；分母为 0 时取 0。",
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
    parser = argparse.ArgumentParser(description="初始化营销中心总部分摊（PER-02）指标")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="CRM 接口域名")
    parser.add_argument("--connection-name", default=CONNECTION_NAME, help="连接名称")
    args = parser.parse_args()

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
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        # 本系列不新增接口：不建来源对象、不建同步任务，仅写指标定义
        for spec in METRICS:
            code = spec["code"]
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
            if spec["kind"] == "metric_scale":
                scale = float(spec["scale"])
                component_codes = [str(item) for item in spec["component_metric_codes"]]
                metric.measures = {
                    "kind": "metric_scale",
                    "component_metric_codes": component_codes,
                    "scale": scale,
                }
                metric.formula = f"({REV01_CODE} 当期值) × {scale * 100:g}%"
                source_text = f"数据来源：本系统内 {REV01_CODE}（对外出货未税销售额（净额））当期结果折算；"
            elif spec["kind"] == "metric_diff":
                # 差额指标：加项合计 − 减项合计（如边际贡献 = 总收益 − 变动费用合计）
                addend_codes = [str(item) for item in spec["addend_metric_codes"]]
                subtrahend_codes = [str(item) for item in spec["subtrahend_metric_codes"]]
                metric.measures = {
                    "kind": "metric_diff",
                    "addend_metric_codes": addend_codes,
                    "subtrahend_metric_codes": subtrahend_codes,
                }
                metric.formula = "SUM(" + " + ".join(addend_codes) + ") - SUM(" + " + ".join(subtrahend_codes) + ")"
                source_text = (
                    f"数据来源：本系统内 {len(addend_codes)} 个加项指标当期结果合计"
                    f" − {len(subtrahend_codes)} 个减项指标当期结果合计；"
                )
            elif spec["kind"] == "metric_ratio":
                # 比率指标：分子合计 ÷ 分母合计 × ratio_scale（如边际贡献率 = 边际贡献 ÷ 总收益 × 100%)
                # 分子/分母可各带一组减项（加项之和 − 减项之和，如安全边际率的分子是「总收益 − 盈亏平衡点销售额」）
                numerator_codes = [str(item) for item in spec["numerator_metric_codes"]]
                denominator_codes = [str(item) for item in spec["denominator_metric_codes"]]
                numerator_subtrahend_codes = [
                    str(item) for item in spec.get("numerator_subtrahend_metric_codes") or []
                ]
                denominator_subtrahend_codes = [
                    str(item) for item in spec.get("denominator_subtrahend_metric_codes") or []
                ]
                ratio_scale = float(spec.get("ratio_scale") or 1)
                metric.measures = {
                    "kind": "metric_ratio",
                    "numerator_metric_codes": numerator_codes,
                    "denominator_metric_codes": denominator_codes,
                    "ratio_scale": ratio_scale,
                }
                if numerator_subtrahend_codes:
                    metric.measures["numerator_subtrahend_metric_codes"] = numerator_subtrahend_codes
                if denominator_subtrahend_codes:
                    metric.measures["denominator_subtrahend_metric_codes"] = denominator_subtrahend_codes
                numerator_text = " + ".join(numerator_codes) + "".join(
                    f" - {code}" for code in numerator_subtrahend_codes
                )
                denominator_text = " + ".join(denominator_codes) + "".join(
                    f" - {code}" for code in denominator_subtrahend_codes
                )
                metric.formula = (
                    f"SUM({numerator_text}) / SUM({denominator_text})"
                    + (f" × {ratio_scale:g}" if ratio_scale != 1 else "")
                )
                if spec.get("unit"):
                    # 分母是百分数/天数等非金额口径时结果可能不是百分数，按指标显式声明的单位输出
                    # 注意：JSON 字段必须整体重新赋值，原地改 dict 不会被 SQLAlchemy 追踪
                    metric.measures = {**metric.measures, "unit": str(spec["unit"])}
                    metric.formula += f"（单位：{spec['unit']}）"
                source_text = (
                    f"数据来源：本系统内 {len(numerator_codes)} 个分子指标当期结果合计"
                    f" ÷ {len(denominator_codes)} 个分母指标当期结果合计；"
                )
            else:
                component_codes = [str(item) for item in spec["component_metric_codes"]]
                metric.measures = {"kind": "metric_sum", "component_metric_codes": component_codes}
                metric.formula = "SUM(" + " + ".join(component_codes) + ")"
                source_text = f"数据来源：本系统内 {len(component_codes)} 个 PER-02 组成指标当期结果合计；"
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{spec['rule']} {PCT_RULE} {source_text}"
                "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

        print(f"CRM 连接 id={connection.id}，来源系统 id={system.id}（本系列无同步任务）")

    await async_engine.dispose()
    print("营销中心总部分摊（PER-02）指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
