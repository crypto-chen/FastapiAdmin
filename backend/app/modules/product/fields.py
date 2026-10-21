"""产品线分析字段注册表（PRD-00 ~ PRD-44，唯一事实来源）。

结构对齐 ``app/modules/customer/fields.py``（客户分析 CUS-xx），便于两个报表共用构建框架。

约定：

- ``field_code`` 直接用底稿编码（PRD-00 ~ PRD-44）；底稿无编码的 12 个明细/派生项
  按底稿出现顺序补 ``PRD-X01 ~ PRD-X12``。
- ``source`` 记录底稿来源列（系统 / ERP / ERP/BOM / CRM / 平台后台 / 银行收款单 /
  费用表 / 分摊表 / 总账 / 计算）。
- ``status`` 记录取数可出性，取值见 ``STATUS_*``：这是本报表开工前唯一的
  「能不能出数」事实来源，构建时按状态决定写值还是只写口径说明。
- ``sensitive`` 标记成本毛利类字段，对外开放接口据此裁剪。

产品线主数据源（2026-10-15 业务确认）：**CRM 产品型号字典**
``/hs/product/getProductModel``（型号字典，实测 523 行、字段 id / category_id / model /
width / length / height），搭配**订单分析接口** ``/hs/order/orderAnalyze?type=1|2|3`` 使用
（``type=3`` 为 2026-10-21 新增的零售订单范围）。

**SKU 就取型号字典的 ``model``**（型号编码，如 J01B），不取 id、不取名称。
**产品名称、规格不做**（2026-10-15 业务确认）：型号字典的 ``width / length / height``
本报表不取，PRD-03 / PRD-04 维持划掉状态。

取数链路与实测覆盖：

=====  ====================================================================  ==========
链路     取数                                                                  实测
=====  ====================================================================  ==========
型号     订单行 ``product_model``（数值 = 型号 id）→ 型号字典 ``id``                164,112 / 167,673（97.88%）
型号名   → 型号字典 ``model``（如 J01B）                                        523 个型号
产品线   → 型号字典 ``category_id`` → 系列字典 ``/hs/product/getProductCategory``  522 / 523 可对上
上卷     沿系列字典父链上卷到「产品分类」下的一级节点，**不建对照表**              97.88%
兜底     型号未命中时用订单行 ``product_series`` 直接上卷                         99.82%
=====  ====================================================================  ==========

实测产品线大类分布：壳体 80.3%、机箱 9.1%、钣金外壳 2.9%、面板 2.0%、
其它（有壳体的尺寸，还没确定系列）1.8%、模具 0.8%、影音功放 0.3%、拉手 0.3%、
CNC外壳 0.2%、服务费 0.1%、新产品 0.02%。

上卷实现见 ``app/modules/customer/build.py::product_line_map``（客户分析已复用同一逻辑）；
型号字典 → 系列字典的关联已由 ``app/modules/order/build.py`` 落进
``dwd_order_full_chain.extra``（``sku_id`` / ``sku`` / ``product_series_id`` / ``product_series``）。
"""

from __future__ import annotations

# 产品线维度的来源对象（均为已注册、已在同步的来源对象）
PRODUCT_MODEL_OBJECT = "/hs/product/getProductModel"  # 型号字典｜产品线主数据源
PRODUCT_CATEGORY_OBJECT = "/hs/product/getProductCategory"  # 系列字典｜上卷产品线大类
ORDER_ANALYZE_DOMESTIC_OBJECT = "/hs/order/orderAnalyze?type=1"  # 订单分析（内贸）
ORDER_ANALYZE_EXPORT_OBJECT = "/hs/order/orderAnalyze?type=2"  # 订单分析（外贸）
ORDER_ANALYZE_RETAIL_OBJECT = "/hs/order/orderAnalyze?type=3"  # 订单分析（零售）

# 实际成本来源：金蝶「成本计算单」（2026-10-16 业务更正 —— 实际成本取 ERP 成本计算单，按订单取）
COST_BILL_OBJECT = "CB_CostCalBill"  # GetSysReportData 的 formid

# 已实测打通的取数参数（2026-10-16，业务给定模板，原样透传见
# exports/cost_bill/request_cb_org100_2026-09.json）
COST_BILL_CONFIRMED_PARAMS: dict[str, str] = {
    "FACCTGORGID.FNumber": "100",  # 核算组织编码（成本计算在主体组织；101~113 均返回 0 行）
    "FACCTPOLICYID.FNumber": "KJZC01_SYS",  # 会计政策编码（中国准则会计政策）
    "FACCTGSYSTEMID.FNumber": "KJHSTX01_SYS",  # 核算体系编码
    "FSHOWWAY": "2",  # 显示方式
    "FCurrencyID.FNumber": "PRE001",  # 币别（人民币）
    # 实测（2026-09，组织 100，2000 行抽样）：
    #   FOrderBillNo     1999/2000 有值（= 销售订单号-产品编码 拼接）
    #   FPRODUCTNO       2000/2000 有值（= 工单编号，纯单号）
    #   FSumProductUseCost 1892/2000 有值（累计单位成本，按订单取实际成本用这列）
    #   FProductUseCost      2/2000 有值（本期单位成本，仅当期完工的行有）
    #   FCOSTITEMID_FNAME / FEXPENSEITEMFIELD_FNAME / FMATERIALFIELD_FNAME 恒空；
    #   FSHOWWAY=3/4 + 明细开关都为空，FSHOWWAY=1 时报表超重（360s 读超时）
}
COST_BILL_REQUIRED_PARAMS: tuple[str, ...] = tuple(COST_BILL_CONFIRMED_PARAMS)

# 底稿指标 → 成本计算单显示列（FieldKeys）
COST_BILL_FIELDS: dict[str, str] = {
    "PRD-05": "FBOMNUMBERFIELD_FNUMBER",
    "PRD-06": "FProductUseCost / FSumProductUseCost",
    "PRD-08": "FCOSTITEMID_FNAME + FCurrInputAmount / FCompleteAmount",
    "PRD-09": "FEXPENSEITEMFIELD_FNAME + FCurrInputAmount",
    "PRD-10": "FEXPENSEITEMFIELD_FNAME + FCurrInputAmount",
}

# 成本计算单的订单关联列（按订单取实际成本）
COST_BILL_ORDER_KEYS: tuple[str, ...] = ("FOrderBillNo", "FOrderBillSeq", "FPRODUCTNO", "FPRODUCTID_FNUMBER")

# 底稿来源列 → 系统实际取数来源（构建时按此取数）
DATA_SOURCES: dict[str, str] = {
    "系统": "本系统期间字段（dwd_order_full_chain.period_value）",
    "ERP": "CRM 型号字典 / 聚水潭销售出库 / 金蝶单据（按字段分派）",
    "ERP/BOM": "金蝶成本计算单 CB_CostCalBill（按销售订单号取实际成本；取数参数已打通，2026-10-16）",
    "CRM": "CRM 开放接口（orderAnalyze 等 /hs/*）",
    "平台后台": "CRM 基础分类字典 /hs/base/getBaseCategoryList（编码转名称）",
    "银行收款单": "未接入",
    "费用表": "未接入（现用金蝶科目余额表 GL_RPT_AccountBalance）",
    "分摊表": "未接入（现按对外出货未税净额 × 固定比例折算）",
    "总账": "金蝶科目余额表 GL_RPT_AccountBalance",
    "计算": "本系统内派生指标（metric_def）",
}

# 取数可出性状态
STATUS_READY = "ready"  # 现用数据源可直接出数
STATUS_PENDING_FIELD = "pending_field"  # 来源已有、未落库，需补字段
STATUS_SOURCE_FOUND = "source_found"  # 来源已定位，待打通取数（参数/映射未定）
STATUS_PENDING_CALIBER = "pending_caliber"  # 口径/维度待定，现为替代口径或公司级
STATUS_MISSING = "missing"  # 无来源，出不了
STATUS_DROPPED = "dropped"  # 底稿已划掉

STATUS_LABELS: dict[str, str] = {
    STATUS_READY: "现用可出",
    STATUS_PENDING_FIELD: "需补字段",
    STATUS_SOURCE_FOUND: "来源已定位",
    STATUS_PENDING_CALIBER: "待定口径",
    STATUS_MISSING: "缺数据",
    STATUS_DROPPED: "底稿划掉",
}

# 落物理列的字段（其余全部进 extra JSON）
CORE_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "period_value",
        "calc_version",
        "is_aggregate",
        "product_line_code",
        "product_line_name",
        "sku",
        "order_count",
        "ship_qty",
        "intake_untaxed",
        "ship_untaxed",
        "net_shipment",
        "gross_profit",
        "contribution_margin",
        "data_quality_flag",
    }
)

# (字段编码, 字段名称, 类型, 分组, 是否敏感, 底稿来源, 可出性, 口径/依据说明)
FIELD_DEFS: list[tuple[str, str, str, str, bool, str, str, str]] = [
    # ---- 维度：基础 ----
    ("PRD-00", "期间", "string", "基础", False, "系统", STATUS_READY, "YYYY-MM；取自 dwd_order_full_chain.period_value（2024-10~2026-10 已落库）"),
    ("PRD-01", "产品线大类", "string", "维度", False, "ERP", STATUS_READY, "主数据源 = 型号字典 /hs/product/getProductModel：订单行 product_model → 型号 id → 型号字典 category_id → 系列字典上卷；原值直用不建对照表，实测 97.88%（型号未命中时用订单行 product_series 兜底至 99.82%）"),
    ("PRD-02", "SKU", "string", "维度", False, "ERP", STATUS_READY, "SKU 就取型号字典 /hs/product/getProductModel 的 model（523 个型号，如 J01B；不取 id、不取名称）；订单行命中 164,112/167,673（97.88%）"),
    ("PRD-03", "产品名称", "string", "维度", False, "ERP", STATUS_DROPPED, "底稿已划掉，2026-10-15 业务确认不做；型号字典无名称字段，仍无来源"),
    ("PRD-04", "规格", "string", "维度", False, "ERP", STATUS_DROPPED, "底稿已划掉，2026-10-15 业务确认不做；型号字典的 width/length/height（482/523 有值）本报表不取"),
    # ---- 成本构成 ----
    ("PRD-05", "BOM版本", "string", "成本", False, "ERP/BOM", STATUS_READY, "金蝶成本计算单 CB_CostCalBill 的 FBOMNUMBERFIELD_FNUMBER；按工单号（FPRODUCTNO）关联订单全链路 extra.push_no，同 SKU 取出现次数最多的版本；2026-09 覆盖 174/192 明细行"),
    ("PRD-06", "实际单位成本", "number", "成本", True, "ERP/BOM", STATUS_READY, "成本计算单按工单号关联订单，取本期完工行（FCompleteQty>0）的 FProductUseCost 按 SKU 简单平均；2026-09 覆盖 166/192 明细行"),
        ("PRD-07", "实际材料单位成本", "number", "成本", True, "ERP/BOM", STATUS_READY, "成本计算单：工单材料成本（成本项目=直接材料）÷ 工单完工数量（按单据累加）→ 按 SKU 简单平均；2026-09 覆盖 164/192 明细行"),
        ("PRD-08", "实际人工单位成本", "number", "成本", True, "ERP/BOM", STATUS_DROPPED, "2026-10-17 业务确认去掉人工指标，不做"),
                    ("PRD-09", "实际制造费用单位成本", "number", "成本", True, "ERP/BOM", STATUS_READY, "成本计算单 full 模式：工单制造费用（非材料、非直接人工的费用项目）÷ 工单完工数量（只取单据级汇总行并累加）→ 按 SKU 简单平均；2026-09 覆盖 842/1257 工单"),
        ("PRD-10", "实际制造费用-固定单位", "number", "成本", True, "ERP/BOM", STATUS_DROPPED, "2026-10-17 业务确认并入 PRD-09（制造费用不再分变动/固定），本编码不做"),
    # ---- 数量与标准成本 ----
    ("PRD-11", "出货数量", "number", "数量", False, "ERP", STATUS_READY, "CRM 发货明细 /hs/shipments/getShipmentsDetail（发货时间口径，按 order_id 关联）优先，未命中回退 orderShipments.send_qty；已落 dwd_order_full_chain.ship_qty，2026-09 覆盖 989/1419 单"),
    ("PRD-12", "标准材料成本", "number", "成本", True, "计算", STATUS_READY, "标准成本取 CRM 销售订单：= extra.material_cost_unit × PRD-11；2026-09 覆盖 163/192 明细行"),
        ("PRD-13", "标准人工成本", "number", "成本", True, "计算", STATUS_DROPPED, "2026-10-17 业务确认去掉人工指标，不做"),
            ("PRD-14", "标准制造费用", "number", "成本", True, "CRM", STATUS_READY, "取 CRM 订单分析接口的加工费（process_cost_total ÷ 数量 × PRD-11 出货数量）；2026-09 覆盖 165/192 明细行"),
        ("PRD-15", "标准制造费用-固定", "number", "成本", True, "计算", STATUS_DROPPED, "2026-10-17 业务确认并入 PRD-14（制造费用不再分变动/固定），本编码不做"),
            ("PRD-16", "标准成本小计", "number", "成本", True, "计算", STATUS_READY, "= PRD-12 标准材料成本 + PRD-14 标准制造费用（两项缺一时回退标准单位成本 × 出货量）"),
    ("PRD-17", "单位标准成本", "number", "成本", True, "CRM", STATUS_READY, "标准成本取 CRM 销售订单：extra.unit_cost（订单行 material_cost_total + process_cost ÷ 数量），按数量加权平均；覆盖 98,580/167,673（58.8%）"),
    # ---- 维度：组织与渠道 ----
    ("PRD-18", "业务员", "string", "维度", False, "CRM", STATUS_READY, "salesman_code + salesman_name（master_person 已同步）"),
    ("PRD-19", "订单类型", "string", "维度", False, "CRM", STATUS_READY, "extra.order_type_code → 批量/打样/零售/备货"),
    ("PRD-20", "平台", "string", "维度", False, "平台后台", STATUS_READY, "extra.platform（CRM getBaseCategoryList 编码转名称），覆盖 141,787/167,673；实测无拼多多、抖音"),
    ("PRD-21", "店铺", "string", "维度", False, "平台后台", STATUS_READY, "extra.shop / extra.shop_id，覆盖 167,652/167,673"),
    # ---- 金额链 ----
    ("PRD-22", "接单未税", "number", "金额", False, "CRM", STATUS_READY, "intake_untaxed（Σ 销售订单未税）"),
    ("PRD-23", "货物出货未税", "number", "金额", False, "ERP", STATUS_READY, "ship_untaxed（Σ 销售出库未税），覆盖 94,614/167,673"),
    ("PRD-24", "设计服务收入", "number", "金额", False, "CRM/总账", STATUS_READY, "extra.design_service_income（CRM getShejifei / getDesignAmount）；金蝶科目余额表亦已接入"),
    ("PRD-25", "退货退款", "number", "金额", False, "ERP", STATUS_READY, "extra.return_refund（负数，CRM getReturnOrder / getReturnOrderDetail）"),
    ("PRD-26", "对外出货净额", "number", "金额", False, "计算", STATUS_READY, "net_shipment = PRD-23 + PRD-24 + PRD-25，order/build.py 已实现"),
    ("PRD-27", "营销结算收入10%", "number", "金额", False, "计算", STATUS_READY, "marketing_total_income_settlement = REV-01 × 10%，指标引擎已在跑"),
    ("PRD-28", "回款", "number", "回款", True, "银行收款单", STATUS_MISSING, "无银行收款单来源对象；dwd_order_full_chain.payment_amount 全表为空，仅 collect_date 有值"),
    # ---- 费用与收益 ----
    ("PRD-29", "变动费用分摊", "number", "费用", True, "费用表", STATUS_READY, "2026-10-17 业务确认：按对外出货净额（PRD-26）× 28% 分摊列示（非实际发生额）"),
    ("PRD-30", "边际贡献", "number", "成本", True, "计算", STATUS_READY, "2026-10-17 业务确认：= PRD-26 对外出货净额 − PRD-29 变动费用分摊"),
    ("PRD-31", "边际贡献率", "number", "成本", False, "计算", STATUS_READY, "= PRD-30 边际贡献 ÷ PRD-26 对外出货净额（百分数）；与变动分摊 28% 对应，理论值 72%"),
    ("PRD-32", "固定费用分摊", "number", "费用", True, "分摊表", STATUS_READY, "2026-10-17 业务确认：按对外出货净额（PRD-26）× 6% 分摊列示"),
    ("PRD-33", "总部分摊", "number", "费用", True, "分摊表", STATUS_READY, "marketing_per02_total = 对外出货净额 × 2.00%，与底稿 PRD-27 × 2% 完全一致"),
    ("PRD-34", "结算收益", "number", "成本", True, "计算", STATUS_READY, "底稿 = PRD-30 边际贡献 − PRD-32 固定费用分摊 − PRD-33 总部分摊"),
    ("PRD-35", "结算收益率", "number", "成本", False, "计算", STATUS_READY, "底稿 = PRD-34 ÷ PRD-26 对外出货净额（百分数）"),
    # ---- 库存 ----
    ("PRD-36", "库存", "number", "库存", True, "ERP", STATUS_READY, "2026-10-17 业务确认取 CRM 订单：= 接单余额 + 在制 + 完工齐套未出货（成本口径：未出货数量 × 标准单位成本）"),
    ("PRD-37", "在制", "number", "库存", True, "ERP", STATUS_READY, "CRM 订单：已下推（push_date 有值）且未齐套（finish_date 为空）的未出货成本"),
    ("PRD-38", "完工未出货", "number", "库存", True, "ERP", STATUS_READY, "CRM 订单：已齐套（finish_date 有值）且仍未出库的未出货成本"),
    ("PRD-39", "呆滞库存", "number", "库存", True, "ERP", STATUS_READY, "CRM 订单：齐套入库超 90 天仍未出库的库存成本（按期间末 −90 天判定）"),
    ("PRD-40", "库存周转天数", "number", "库存", False, "计算", STATUS_READY, "= 平均库存（(上期+本期)÷2）÷ 本期销售成本（PRD-16）× 30；与客户分析 CUS-37 同口径"),
    # ---- 毛利 ----
    ("PRD-41", "毛利", "number", "成本", True, "计算", STATUS_READY, "底稿口径（2026-10-17 业务确认不采用替代口径）：= PRD-26 对外出货净额 − PRD-16 标准成本小计"),
    ("PRD-42", "毛利率", "number", "成本", False, "计算", STATUS_READY, "底稿 = PRD-41 ÷ PRD-26（百分数）"),
            ("PRD-43", "标准成本边际贡献", "number", "成本", True, "计算", STATUS_READY, "= PRD-26 对外出货净额 − PRD-12 标准材料成本 − PRD-14 标准制造费用"),
        ("PRD-44", "标准成本边际贡献率", "number", "成本", False, "计算", STATUS_READY, "= PRD-43 ÷ PRD-26（百分数）"),
    # ---- 底稿无编码：明细/派生项（按底稿出现顺序补编码） ----
    ("PRD-X01", "订单数量", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；CRM getOrderCount + orderAnalyze 按订单号去重"),
    ("PRD-X02", "客单价", "number", "数量", False, "计算", STATUS_READY, "底稿无编码；= PRD-27 ÷ PRD-X01"),
    ("PRD-X03", "平均产品单价", "number", "数量", False, "计算", STATUS_READY, "底稿无编码；= PRD-26 对外出货净额 ÷ PRD-11 出货数量，2026-09 合计 51.6798"),
    ("PRD-X04", "打样金额", "number", "金额", False, "CRM", STATUS_READY, "底稿无编码；order_type=打样 的 intake_untaxed 汇总"),
    ("PRD-X05", "打样数量", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；order_type=打样 的 qty 汇总"),
    ("PRD-X06", "打样平均单价", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；= PRD-X04 ÷ PRD-X05"),
    ("PRD-X07", "批量金额", "number", "金额", False, "CRM", STATUS_READY, "底稿无编码；order_type=批量 的 intake_untaxed 汇总"),
    ("PRD-X08", "批量数量", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；order_type=批量 的 qty 汇总"),
    ("PRD-X09", "批量平均单价", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；= PRD-X07 ÷ PRD-X08"),
    ("PRD-X10", "零售金额", "number", "金额", False, "CRM", STATUS_READY, "底稿无编码；order_type=零售 的 intake_untaxed 汇总"),
    ("PRD-X11", "零售数量", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；order_type=零售 的 qty 汇总"),
    ("PRD-X12", "零售平均单价", "number", "数量", False, "CRM", STATUS_READY, "底稿无编码；= PRD-X10 ÷ PRD-X11"),
    # ---- 底稿无编码、2026-10-16 业务确认产品线报表**不做**的项 ----
    ("PRD-X13", "总劳动时间", "number", "人工", False, "CRM", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做（公司级有 marketing_total_labor_hours，本报表不用）"),
    ("PRD-X14", "人工成本", "number", "人工", True, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做"),
    ("PRD-X15", "人工分摊", "number", "人工", True, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做"),
    ("PRD-X16", "单位时间附加值", "number", "人工", True, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做（公司级有 marketing_value_added_per_hour）"),
    ("PRD-X17", "单位时间人工成本", "number", "人工", True, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做"),
    ("PRD-X18", "贡献率", "number", "贡献", False, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做"),
    ("PRD-X19", "产品贡献", "number", "贡献", True, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做"),
    ("PRD-X20", "产品贡献率", "number", "贡献", False, "计算", STATUS_DROPPED, "2026-10-16 业务确认产品线报表不做"),
]

FIELD_BY_CODE: dict[str, tuple[str, str, str, str, bool, str, str, str]] = {
    item[0]: item for item in FIELD_DEFS
}

# 本期未出数的字段：构建时留空，只写口径说明
PENDING_CODES: frozenset[str] = frozenset(
    code
    for code, *_rest in FIELD_DEFS
    if _rest[5] in (STATUS_PENDING_FIELD, STATUS_SOURCE_FOUND, STATUS_PENDING_CALIBER)
)

# 来源已定位、待打通取数参数的字段（实际成本来自金蝶成本计算单）
SOURCE_FOUND_CODES: frozenset[str] = frozenset(
    code for code, *_rest in FIELD_DEFS if _rest[5] == STATUS_SOURCE_FOUND
)

# 无来源、出不了的字段
MISSING_CODES: frozenset[str] = frozenset(
    code for code, *_rest in FIELD_DEFS if _rest[5] == STATUS_MISSING
)

# 底稿已划掉
DROPPED_CODES: frozenset[str] = frozenset(
    code for code, *_rest in FIELD_DEFS if _rest[5] == STATUS_DROPPED
)

# 2026-10-16 业务确认产品线报表不做的项（底稿无编码，补 PRD-X13 ~ PRD-X20）
BUSINESS_EXCLUDED_CODES: frozenset[str] = frozenset(
    {
        "PRD-X13",  # 总劳动时间
        "PRD-X14",  # 人工成本
        "PRD-X15",  # 人工分摊
        "PRD-X16",  # 单位时间附加值
        "PRD-X17",  # 单位时间人工成本
        "PRD-X18",  # 贡献率
        "PRD-X19",  # 产品贡献
        "PRD-X20",  # 产品贡献率
    }
)

# 现用数据源可直接出数的字段
READY_CODES: frozenset[str] = frozenset(
    code for code, *_rest in FIELD_DEFS if _rest[5] == STATUS_READY
)

SENSITIVE_CODES: frozenset[str] = frozenset(code for code, *_rest in FIELD_DEFS if _rest[3])

# 多值拼接字段（同一产品线当月多个取值 → 按金额降序 `/` 拼接）
CONCAT_CODES: tuple[str, ...] = ("PRD-01", "PRD-02", "PRD-18", "PRD-19", "PRD-20", "PRD-21")

# 对外输出时的字段顺序
FIELD_ORDER: list[str] = [code for code, *_rest in FIELD_DEFS]


def status_summary() -> dict[str, int]:
    """按可出性汇总字段数（构建自检与对外说明共用）。"""
    summary = {status: 0 for status in STATUS_LABELS}
    for _code, *_rest in FIELD_DEFS:
        summary[_rest[5]] += 1
    return summary
