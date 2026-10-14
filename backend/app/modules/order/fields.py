"""订单全链路字段注册表（字段的唯一事实来源）。

换字段来源、加字段、减字段都只改这个文件：

- ``FIELD_DEFS``：对外字段目录（编码/名称/类型/分组/敏感/落库位置）。
- ``SOURCE_KEYS``：简单字段的取值键与优先级（按顺序取第一个非空值）。
  CRM 2026-10-13 改版后内贸接单未税由 ``remove_taxes_freight`` 改名为 ``amount``，
  两者都写进候选列表即可同时兼容新旧批次。
- 计算字段（成本、周期、净出货等）在 ``build.py`` 的 ``compute`` 分支里实现。
"""

from __future__ import annotations

# 落物理列的字段（其余字段进 extra JSON）
CORE_COLUMNS: frozenset[str] = frozenset(
    {
        "order_number",
        "period_value",
        "calc_version",
        "trade_type",
        "order_type",
        "customer_id",
        "salesman_code",
        "order_date",
        "push_date",
        "finish_date",
        "ship_date",
        "qty",
        "intake_untaxed",
        "ship_untaxed",
        "net_shipment",
    }
)

# 字段目录：(field_code, 名称, 类型, 分组, 是否敏感, 指标编码)
# 指标编码对应财务底稿的 ORD-xx 科目（未列入底稿的字段留空字符串）
FIELD_DEFS: list[tuple[str, str, str, str, bool, str]] = [
    ("order_number", "订单号", "string", "基础", False, "ORD-00"),
    ("period_value", "期间", "string", "基础", False, ""),
    ("trade_type", "贸易类型", "string", "基础", False, "ORD-11"),
    ("order_type", "订单类型", "string", "基础", False, "ORD-10"),
    ("qty", "数量", "number", "基础", False, ""),
    ("sku", "SKU", "string", "基础", False, "ORD-02"),
    ("size", "尺寸", "string", "基础", False, "ORD-03"),
    ("customer_id", "客户ID", "number", "基础", False, ""),
    ("customer_name", "客户", "string", "基础", False, "ORD-04"),
    ("customer_number", "客户编号", "string", "基础", False, ""),
    ("customer_principal", "客户所属业务员编码", "string", "基础", False, ""),
    ("customer_principal_name", "客户所属业务员", "string", "基础", False, ""),
    ("salesman_code", "业务员编码", "string", "基础", False, ""),
    ("salesman_name", "业务员", "string", "基础", False, "ORD-05"),
    ("platform", "平台", "string", "维度", False, "ORD-06"),
    ("shop", "店铺", "string", "维度", False, "ORD-07"),
    ("is_new", "新老客户", "string", "维度", False, "ORD-08"),
    ("product_series", "产品线大类", "string", "维度", False, "ORD-09"),
    ("order_date", "接单日期", "date", "节点", False, "ORD-12"),
    ("push_date", "下推日期", "date", "节点", False, "ORD-17"),
    ("push_no", "下推单号", "string", "节点", False, "ORD-18"),
    ("mo_numbers", "生产工单", "string", "节点", False, "ORD-19"),
    ("finish_date", "齐套入库日期", "date", "节点", False, "ORD-20"),
    ("ship_date", "销售出库日期", "date", "节点", False, "ORD-23"),
    ("promised_date", "预定交期", "date", "节点", False, "ORD-40"),
    ("actual_date", "实际交期", "date", "节点", False, "ORD-41"),
    ("on_time", "是否准时", "string", "节点", False, "ORD-42"),
    ("intake_untaxed", "接单未税", "number", "金额", False, "ORD-13"),
    ("design_fee", "设计费", "number", "金额", False, "ORD-14"),
    ("deposit", "定金", "number", "金额", False, "ORD-16"),
    ("ship_untaxed", "出货未税", "number", "金额", False, "ORD-24"),
    ("design_service_income", "设计服务收入", "number", "金额", False, "ORD-25"),
    ("return_refund", "退货退款", "number", "金额", False, "ORD-26"),
    ("net_shipment", "净出货", "number", "金额", False, "ORD-27"),
    ("inbound_qty", "入库数量", "number", "生产", False, "ORD-21"),
    ("inbound_untaxed", "入库未税", "number", "生产", False, "ORD-22"),
    ("unit_cost", "标准单位成本", "number", "成本", True, "ORD-58"),
    ("material_cost_unit", "标准材料成本", "number", "成本", True, "ORD-59"),
    ("material_cost_basis", "材料成本（标准材料成本×入库数量）", "number", "成本", True, ""),
    ("total_cost", "订单总成本", "number", "成本", True, ""),
    ("cost_basis", "毛利扣减成本（单位成本×入库数量）", "number", "成本", True, ""),
    ("gross_profit", "订单毛利", "number", "成本", True, "ORD-65"),
    ("gross_profit_rate", "订单毛利率", "number", "成本", True, "ORD-66"),
    ("contribution_margin", "订单边际贡献", "number", "成本", True, "ORD-67"),
    ("contribution_margin_rate", "订单边际贡献率", "number", "成本", True, "ORD-68"),
    ("collect_date", "收款日期", "date", "回款", False, "ORD-15"),
    ("payment_date", "回款日期", "date", "回款", False, "ORD-28"),
    ("payment_amount", "回款金额", "number", "回款", True, "ORD-29"),
    ("ar_balance", "应收余额", "number", "回款", True, "ORD-30"),
    ("overdue_days", "逾期天数", "number", "回款", False, "ORD-32"),
    ("inventory_status", "库存状态", "string", "状态", False, "ORD-33"),
    ("push_period", "下推周期", "number", "周期", False, "ORD-34"),
    ("production_cycle", "生产周期", "number", "周期", False, "ORD-35"),
    ("ship_cycle", "出货周期", "number", "周期", False, "ORD-36"),
    ("full_cycle", "订单全周期", "number", "周期", False, "ORD-37"),
    ("cost_source", "成本来源", "string", "质量", False, ""),
    ("data_quality_flag", "数据质量标记", "string", "质量", False, ""),
]

FIELD_BY_CODE: dict[str, tuple[str, str, str, str, bool, str]] = {item[0]: item for item in FIELD_DEFS}

# 简单字段：按顺序取第一个非空值（兼容 CRM 新旧字段名）
SOURCE_KEYS: dict[str, list[str]] = {
    "qty": ["qty"],
    "size": ["size"],
    "customer_id": ["customer"],
    # 客户名称以「客户列表接口」为准（见 build.py），订单上的 customer_name/customer_name_retail 只作兜底；
    # 注意：``wangwang`` 是旺旺号/客户备注，不是客户名称，不能当客户名用。
    "customer_name": ["customer_name", "customer_name_retail"],
    "salesman_code": ["create_id"],
    "order_type": ["order_type"],
    "platform": ["source_platform"],
    # 店铺取 orderAnalyze 的 source 字段（业务口径确认）；store_name 是外贸侧的另一套编码
    "shop": ["source"],
    # SKU 取 product_model（业务口径确认）
    "sku": ["product_model"],
    "is_new": ["is_new"],
    "product_series": ["product_series"],
    "design_fee": ["design_remove_taxes_freight", "design_cost"],
    "deposit": ["deposit"],
    "collect_date": ["collectiontime"],
    "payment_date": ["final_paymenttime"],
    # 下推单号＝生产工单号（金蝶 PRD_MO 单据编号），由 build.py 关联生产订单时写入；
    # CRM 侧没有独立的「下推单号」字段，这里保留候选键仅为兼容将来上游补字段。
    "push_no": ["erp_push_no", "push_no"],
    "inventory_status": ["chuhuo"],
    "promised_date": ["deliverytime"],
}

# 接单未税：内贸新旧名 + 外贸
INTAKE_KEYS_DOMESTIC: list[str] = ["remove_taxes_freight", "amount"]
INTAKE_KEYS_EXPORT: list[str] = ["receivable_CNY"]

# 成本：2026-10-13 新版字段名 + 旧字段名兜底
MATERIAL_COST_KEYS: list[str] = ["material_cost_total", "material_cost"]
PROCESS_COST_KEYS: list[str] = ["process_cost_total", "process_cost"]

# 时间字段（CRM 传入可能是 unix 秒或 "YYYY-MM-DD HH:MM:SS"）
DATETIME_KEYS: dict[str, list[str]] = {
    "push_date": ["erp_push_date"],
    "finish_date": ["finish_date"],
    "ship_date": ["chuhuo_date"],
}

# 四舍五入位数
MONEY_SCALE = 4
RATE_SCALE = 6
