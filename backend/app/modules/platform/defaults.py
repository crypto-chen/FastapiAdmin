"""平台分析默认指标清单（首次部署/恢复默认时写入 platform_metric_def）。

编码与业务表一致（PLT-00 ~ PLT-44，划掉的 06/07/10/32/33/34/35 不建）；
可出性 readiness：

- ready   现用可出（表达式已实现，页面/接口直接出数）
- pending 待确认（口径或归属规则未定，先占位）
- todo    待做（缺录入/缺接口/依赖上游指标）
- missing 缺数据源

辅助字段用 ``PLT-Axx``（不在业务表里，但页面/接口需要：订单数、店铺编号等）。
新增指标：管理端「指标配置」或 ``scripts/seed_platform_metrics.py``。
"""

from typing import Any

# 基础聚合量（代码里唯一硬编码的取数逻辑）
BASE_VARIABLES: dict[str, str] = {
    "orders": "订单数（排除 Delete，含取消单）",
    "shipped_orders": "已发货订单数（Sent）",
    "cancelled_orders": "取消单数（Cancelled）",
    "intake": "接单未税（含取消单金额）",
    "shipment": "出货未税（已发货订单）",
    "cancelled_amount": "取消单未税金额（负数）",
    "refund": "发货后售后实退未税（负数）",
    "tax_rate": "税率（13 表示 13%）",
    "settlement_rate": "营销结算比例（0.1 表示 10%）",
    "hq_rate": "总部分摊比例（0.04 表示 4%）",
}

DEFAULT_METRICS: list[dict[str, Any]] = [
    # ── 维度 ──────────────────────────────────────────────
    {"code": "PLT-00", "name": "期间", "group": "维度", "data_type": "string",
     "expression": "period", "note": "订单归属期间 YYYY-MM", "sort": 10, "readiness": "ready"},
    {"code": "PLT-01", "name": "平台", "group": "维度", "data_type": "string",
     "expression": "platform", "note": "由 retail_shop.shop_site 归一：天猫/京东/拼多多/抖音/小红书/1688/其他",
     "sort": 20, "readiness": "ready"},
    {"code": "PLT-02", "name": "店铺", "group": "维度", "data_type": "string",
     "expression": "shop_name", "note": "店铺名称，缺主数据时回退订单上的 shop_name", "sort": 30, "readiness": "ready"},
    {"code": "PLT-03", "name": "运营人员", "group": "维度", "data_type": "string",
     "expression": "", "note": "待确认：需要「店铺 → 运营人员」映射表（CRM 人员 + retail_shop 绑定）",
     "sort": 40, "readiness": "pending"},
    {"code": "PLT-04", "name": "产品线大类", "group": "维度", "data_type": "string",
     "expression": "", "note": "待做：需要 SKU → 产品线字典（CRM 52 个分类映射）", "sort": 50, "readiness": "todo"},
    {"code": "PLT-05", "name": "SKU", "group": "维度", "data_type": "string",
     "expression": "", "note": "待做：需要按 店铺×SKU 汇总 retail_order_item（做明细宽表）", "sort": 60, "readiness": "todo"},

    # ── 数量（辅助） ──────────────────────────────────────
    {"code": "PLT-A01", "name": "店铺编号", "group": "数量", "data_type": "number",
     "expression": "shop_id", "note": "聚水潭 shop_id（辅助字段）", "sort": 70, "readiness": "ready"},
    {"code": "PLT-A02", "name": "订单数", "group": "数量", "data_type": "number", "unit": "单",
     "expression": "orders", "note": "期间内有效订单（排除 Delete，含取消单）", "sort": 80, "readiness": "ready"},
    {"code": "PLT-A03", "name": "已发货单数", "group": "数量", "data_type": "number", "unit": "单",
     "expression": "shipped_orders", "note": "订单状态命中 RETAIL_SHIPPED_STATUSES（默认 Sent）",
     "sort": 90, "readiness": "ready"},
    {"code": "PLT-A04", "name": "取消单数", "group": "数量", "data_type": "number", "unit": "单",
     "expression": "cancelled_orders", "note": "订单状态命中 RETAIL_CANCELLED_STATUSES（默认 Cancelled）",
     "sort": 100, "readiness": "ready"},

    # ── 金额：可出 ────────────────────────────────────────
    {"code": "PLT-08", "name": "接单未税", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "intake", "note": "Σ 买家实付 ÷ (1 + tax_rate/100)，含后续取消的单", "sort": 110, "readiness": "ready"},
    {"code": "PLT-09", "name": "货物出货未税", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "shipment", "note": "已发货订单金额 ÷ 1.13（订单已发货即算货物出货）", "sort": 120, "readiness": "ready"},
    {"code": "PLT-11", "name": "退货退款", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "cancelled_amount + refund", "note": "-(取消单 + 发货后售后) ÷ 1.13，负数", "sort": 130, "readiness": "ready"},
    {"code": "PLT-12", "name": "对外出货净额", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "shipment + PLT-11", "note": "PLT-09 + PLT-11", "sort": 140, "readiness": "ready"},
    {"code": "PLT-13", "name": "营销结算收入10%", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "PLT-12 * settlement_rate", "note": "PLT-12 × 10%（RETAIL_SETTLEMENT_RATE 可配）",
     "sort": 150, "readiness": "ready"},
    {"code": "PLT-23", "name": "总部分摊", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "PLT-13 * hq_rate", "note": "PLT-13 × 4%（RETAIL_HQ_ALLOCATION_RATE 可配），符号与 PLT-13 一致",
     "sort": 160, "readiness": "ready"},

    # ── 金额：待做（需录入/对账/上游） ────────────────────
    {"code": "PLT-14", "name": "平台费", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：需平台账单录入（月初预算、月末实际）", "sort": 170, "readiness": "todo"},
    {"code": "PLT-15", "name": "推广费", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：需平台后台/广告后台导出", "sort": 180, "readiness": "todo"},
    {"code": "PLT-16", "name": "国内快递费", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：需快递对账表（不能用订单买家运费代替）", "sort": 190, "readiness": "todo"},
    {"code": "PLT-17", "name": "国际快递费", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：需货代/快递对账", "sort": 200, "readiness": "todo"},
    {"code": "PLT-18", "name": "售后费用", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：需售后系统费用（≠退货退款金额）", "sort": 210, "readiness": "todo"},
    {"code": "PLT-19", "name": "变动费用小计", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：PLT-14+15+16+17+18（依赖待做指标）", "sort": 220, "readiness": "todo"},
    {"code": "PLT-20", "name": "边际贡献", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：PLT-13 - PLT-19", "sort": 230, "readiness": "todo"},
    {"code": "PLT-21", "name": "边际贡献率", "group": "比率", "data_type": "percent",
     "expression": "", "note": "待做：PLT-20 ÷ PLT-13", "sort": 240, "readiness": "todo"},
    {"code": "PLT-22", "name": "固定费用分摊", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待确认：总账费用按收入/面积/人数分摊的规则未定", "sort": 250, "readiness": "pending"},
    {"code": "PLT-24", "name": "结算收益", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：PLT-21 - PLT-22 - PLT-23", "sort": 260, "readiness": "todo"},
    {"code": "PLT-25", "name": "结算收益率", "group": "比率", "data_type": "percent",
     "expression": "", "note": "待做：PLT-24 ÷ PLT-13", "sort": 270, "readiness": "todo"},
    {"code": "PLT-26", "name": "人工成本", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待做：需薪酬系统按店铺/平台归属", "sort": 280, "readiness": "todo"},
    {"code": "PLT-27", "name": "总劳动时间", "group": "数量", "data_type": "number", "unit": "小时",
     "expression": "", "note": "待确认：需考勤工时 + 人员→店铺归属", "sort": 290, "readiness": "pending"},
    {"code": "PLT-28", "name": "单位时间附加值", "group": "金额", "data_type": "number", "unit": "元/小时",
     "expression": "", "note": "待做：PLT-24 ÷ PLT-27", "sort": 300, "readiness": "todo"},
    {"code": "PLT-29", "name": "贡献率", "group": "比率", "data_type": "percent",
     "expression": "", "note": "待做：PLT-28 ÷ (PLT-26 ÷ PLT-27)，等价 PLT-24 ÷ PLT-26",
     "sort": 310, "readiness": "todo"},
    {"code": "PLT-30", "name": "回款", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "", "note": "待确认：需银行/金蝶收款单与店铺映射", "sort": 320, "readiness": "pending"},
    {"code": "PLT-31", "name": "回款及时率", "group": "比率", "data_type": "percent",
     "expression": "", "note": "待做：PLT-30 ÷ PLT-08", "sort": 330, "readiness": "todo"},

    # ── 比率：可出 ────────────────────────────────────────
    {"code": "PLT-37", "name": "退货率", "group": "比率", "data_type": "percent",
     "expression": "abs(PLT-11) / choose(PLT-12 > 0, PLT-12, PLT-09)",
     "note": "|PLT-11| ÷ PLT-12；PLT-12 ≤ 0 时改用 PLT-09 作分母", "sort": 340, "readiness": "ready"},
    {"code": "PLT-38", "name": "客单价", "group": "比率", "data_type": "number", "unit": "元/单",
     "expression": "PLT-08 / max(PLT-A02 - PLT-A04, 1)",
     "note": "PLT-08 ÷ 有效订单数（订单数 - 取消单数）", "sort": 350, "readiness": "ready"},

    # ── 推广 / 线索 / 复购：待确认与待做 ──────────────────
    {"code": "PLT-36", "name": "推广ROI", "group": "比率", "data_type": "number",
     "expression": "", "note": "待做：【推广带来收入（店铺零售业绩+线索收入）】÷ PLT-15", "sort": 360, "readiness": "todo"},
    {"code": "PLT-39", "name": "线索数量", "group": "数量", "data_type": "number", "unit": "条",
     "expression": "", "note": "待确认：需 CRM 线索接口/平台后台", "sort": 370, "readiness": "pending"},
    {"code": "PLT-40", "name": "成交线索数量", "group": "数量", "data_type": "number", "unit": "条",
     "expression": "", "note": "待确认：CRM 线索成交标记", "sort": 380, "readiness": "pending"},
    {"code": "PLT-41", "name": "线索转化率", "group": "比率", "data_type": "percent",
     "expression": "", "note": "待做：PLT-40 ÷ PLT-39", "sort": 390, "readiness": "todo"},
    {"code": "PLT-42", "name": "线索平均成本", "group": "金额", "data_type": "number", "unit": "元/条",
     "expression": "", "note": "待做：PLT-15 ÷ PLT-39", "sort": 400, "readiness": "todo"},
    {"code": "PLT-43", "name": "成交线索平均成本", "group": "金额", "data_type": "number", "unit": "元/条",
     "expression": "", "note": "待做：PLT-15 ÷ PLT-40", "sort": 410, "readiness": "todo"},
    {"code": "PLT-44", "name": "复购率", "group": "比率", "data_type": "percent",
     "expression": "", "note": "待确认：retail_order.buyer_id 可算，但游客/脱敏 ID 需先定口径",
     "sort": 420, "readiness": "pending"},

    # ── 辅助金额 ──────────────────────────────────────────
    {"code": "PLT-A05", "name": "取消未税", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "cancelled_amount", "note": "取消单金额 ÷ 1.13，负数（已并入 PLT-11）", "sort": 430, "readiness": "ready"},
    {"code": "PLT-A06", "name": "售后未税", "group": "金额", "data_type": "number", "unit": "元", "sensitive": True,
     "expression": "refund", "note": "只含发货后申请的售后实退，负数（PLT-11 = 取消 + 该字段）",
     "sort": 440, "readiness": "ready"},
]
