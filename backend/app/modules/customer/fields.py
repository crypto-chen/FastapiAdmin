"""客户分析字段注册表（CUS-xx，唯一事实来源）。

口径见 ``docs/营销中心客户分析报表方案.md`` §4：

- ``field_code`` 直接用 Excel 底稿编码（CUS-00 ~ CUS-43 / CUS-36-1），
  无编码的 4 个扩展字段用 CUS-44 ~ CUS-47。
- ``source`` 记录底稿来源（系统 / CRM / ERP / 财经 / 合同 / 计算）。
- ``sensitive`` 标记成本毛利类字段，对外开放接口据此裁剪。
"""

from __future__ import annotations

# 落物理列的字段（其余全部进 extra JSON）
CORE_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "period_value",
        "calc_version",
        "is_aggregate",
        "customer_id",
        "customer_code",
        "customer_name",
        "salesman_code",
        "salesman_name",
        "order_count",
        "intake_untaxed",
        "net_shipment",
        "gross_profit",
        "contribution_margin",
        "data_quality_flag",
    }
)

# (字段编码, 字段名称, 类型, 分组, 是否敏感, 底稿来源, 指标编码/说明)
FIELD_DEFS: list[tuple[str, str, str, str, bool, str, str]] = [
    ("CUS-00", "所属期间", "string", "基础", False, "系统", "年-月"),
    ("CUS-01", "客户编码", "string", "基础", False, "CRM", "客户主档 number"),
    ("CUS-02", "客户名称", "string", "基础", False, "CRM", "客户主档 name"),
    ("CUS-03", "客户类型", "string", "维度", False, "CRM", "订单行 customer_category → 字典"),
    ("CUS-04", "地区", "string", "维度", False, "CRM", "客户主档：内贸 region(省/市/区)｜外贸 country(国家，数字ID 经 /hs/base/getBaseWorldList 翻译)"),
    ("CUS-05", "贸易类型", "string", "维度", False, "CRM", "接口 type=1/2；多值拼接"),
    ("CUS-06", "信用等级", "string", "维度", False, "财经", "A/B/C/D（待财经给表）"),
    ("CUS-07", "账期", "string", "维度", False, "合同", "天数（collection_term 编码需映射）"),
    ("CUS-08", "业务员", "string", "维度", False, "CRM", "下单人姓名（多人拼接；编码另存 salesman_code）"),
    ("CUS-09", "产品线大类", "string", "维度", False, "CRM", "product_series 上卷；多值拼接"),
    ("CUS-10", "SKU", "string", "维度", False, "ERP", "product_model；多值拼接"),
    ("CUS-11", "订单类型", "string", "维度", False, "CRM", "order_type；多值拼接"),
    ("CUS-12", "接单未税", "number", "金额", False, "CRM", "Σ 销售订单未税金额"),
    ("CUS-13", "货物出货未税", "number", "金额", False, "ERP", "Σ 销售出库未税"),
    ("CUS-14", "设计服务收入", "number", "金额", False, "CRM/总账", "Σ 设计服务收入"),
    ("CUS-15", "退货退款", "number", "金额", False, "ERP", "Σ 退货退款（负数）"),
    ("CUS-16", "对外出货净额", "number", "金额", False, "计算", "CUS-13 + CUS-14 + CUS-15"),
    ("CUS-17", "营销结算收入10%", "number", "金额", False, "计算", "CUS-16 × 10%"),
    ("CUS-18", "回款", "number", "回款", True, "银行收款单", "Σ 银行收款单（本期待定）"),
    ("CUS-19", "回款及时率", "number", "回款", False, "计算", "CUS-18 ÷ CUS-12（本期待定）"),
    ("CUS-20", "订金回款比例", "number", "回款", False, "计算", "定金回款 ÷ CUS-12（本期待定）"),
    ("CUS-21", "应收余额", "number", "应收", True, "ERP 应收账龄分析表", "时点应收（P1）"),
    ("CUS-22", "逾期应收", "number", "应收", True, "ERP 应收账龄分析表", "超账期金额（P1）"),
    ("CUS-23", "逾期率", "number", "应收", False, "计算", "CUS-22 ÷ CUS-21（P1）"),
    ("CUS-24", "账龄30天", "number", "应收", True, "ERP 应收账龄分析表", "0-30 天金额（P1）"),
    ("CUS-25", "账龄60天", "number", "应收", True, "ERP 应收账龄分析表", "31-60 天金额（P1）"),
    ("CUS-26", "账龄90天", "number", "应收", True, "ERP 应收账龄分析表", "61-90 天金额（P1）"),
    ("CUS-27", "账龄90天以上", "number", "应收", True, "ERP 应收账龄分析表", "91-180 + 181-365 + >365（P1）"),
    ("CUS-28", "毛利", "number", "成本", True, "计算", "CUS-16 − 实际成本"),
    ("CUS-29", "毛利率", "number", "成本", False, "计算", "CUS-28 ÷ CUS-16"),
    ("CUS-30", "边际贡献", "number", "成本", True, "计算", "CUS-17 −(CUS-16/REV-01)×CM-01"),
    ("CUS-31", "边际贡献率", "number", "成本", False, "计算", "CUS-30 ÷ CUS-17"),
    ("CUS-32", "结算收益", "number", "成本", True, "计算", "CUS-30 −(16/REV-01)×CM-04 −(16/REV-01)×PER-02"),
    ("CUS-33", "结算收益率", "number", "成本", False, "计算", "CUS-32 ÷ CUS-17"),
    ("CUS-35", "客户贡献率", "number", "成本", False, "计算", "CUS-32 ÷ REV-01"),
    ("CUS-36", "理论库存", "number", "库存", True, "ERP", "客户已入库未发货的订单成本（Σ cost_basis）"),
    ("CUS-36-1", "实际库存", "number", "库存", True, "ERP", "（待口径）"),
    ("CUS-37", "库存周转天数", "number", "库存", False, "计算", "(上期理论库存+本期理论库存)÷2 ÷ 本期销售订单成本 ×30"),
    ("CUS-38", "呆滞库存", "number", "库存", True, "ERP", "已入库未发货且入库超 90 天的订单成本"),
    ("CUS-40", "复购率", "number", "其他", False, "计算", "复购订单 ÷ 总订单"),
    ("CUS-41", "退货率", "number", "其他", False, "计算", "退货额 ÷ CUS-16"),
    ("CUS-42", "客单价", "number", "其他", False, "计算", "CUS-12 ÷ 接单量"),
    ("CUS-43", "总客户数", "number", "其他", False, "CRM", "客户主档时点总数"),
    ("CUS-44", "创建时间", "string", "其他", False, "ERP", "BD_Customer.FCREATEDATE（待口径）"),
    ("CUS-45", "客户层级", "string", "其他", False, "CRM", "客户标签/客户潜力/机箱客户等级（待选）"),
    ("CUS-46", "行业", "string", "其他", False, "CRM", "客户公司行业（接口待补字段）"),
    ("CUS-47", "下单频次", "number", "其他", False, "计算", "订单数 ÷ 客户数"),
]

FIELD_BY_CODE: dict[str, tuple[str, str, str, str, bool, str, str]] = {item[0]: item for item in FIELD_DEFS}

# 本期不做（挂起/待上游）的字段：构建时留空，只写口径说明
PENDING_CODES: frozenset[str] = frozenset(
    {"CUS-06", "CUS-07", "CUS-18", "CUS-19", "CUS-20", "CUS-36", "CUS-36-1", "CUS-37", "CUS-38", "CUS-44", "CUS-45", "CUS-46"}
)

SENSITIVE_CODES: frozenset[str] = frozenset(code for code, *_rest in FIELD_DEFS if _rest[3])

# 多值拼接字段（同一客户当月多个取值 → 按金额降序 `/` 拼接）
CONCAT_CODES: tuple[str, ...] = ("CUS-05", "CUS-09", "CUS-10", "CUS-11")

# 对外输出时的字段顺序
FIELD_ORDER: list[str] = [code for code, *_rest in FIELD_DEFS]
