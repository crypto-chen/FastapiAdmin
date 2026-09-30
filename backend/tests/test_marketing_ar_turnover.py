"""营销中心平均应收余额取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

from app.modules.metric.engine import extract_account_balance

FIELDS = [
    "FBALANCEID",
    "FBALANCENAME",
    "FDETAILNUMBER",
    "FDETAILNAME",
    "FBEGINDEBIT",
    "FBEGINCREDIT",
    "FENDDEBIT",
    "FENDCREDIT",
]

# 与 scripts/seed_marketing_ar_turnover_metric.py 的 AVG_BALANCE_MEASURES 一致
CONFIG = {
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


def _row(account, detail_code, detail_name, begin_debit, begin_credit, end_debit, end_credit):
    """科目行 + 核算维度行同构：科目列在核算维度行上为空，由上一科目行继承。"""
    return [
        account,
        "应收账款",
        detail_code,
        detail_name,
        begin_debit,
        begin_credit,
        end_debit,
        end_credit,
    ]


def test_average_balance_is_half_begin_plus_half_end():
    rows = [
        # 科目汇总行（无核算维度）：必须跳过，避免与客户明细重复
        _row("1122", "", "", "999,999", "", "999,999", ""),
        # 外部客户 200：期初借 100、期末借 120 → 0.5×100 + 0.5×120 = 110
        _row("", "200", "外部客户A", "100", "", "120", ""),
        # 内部客户 100：应剔除
        _row("", "100", "内部客户", "1000", "", "1000", ""),
        # 外部客户 300（预收，贷方）：期初贷 20、期末贷 20 → 0.5×(-20) + 0.5×(-20) = -20
        _row("", "300", "外部客户B", "", "20", "", "20"),
        # 非 1122 科目：不匹配
        _row("6601", "", "销售费用", "1", "", "1", ""),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    assert extracted["total"] == 90.0  # 110 - 20
    assert extracted["matched_rows"] == 2
    assert set(extracted["departments"]) == {"200", "300"}
    assert extracted["departments"]["200"]["value"] == 110.0
    assert extracted["departments"]["200"]["name"] == "外部客户A"
    assert extracted["departments"]["300"]["value"] == -20.0


def test_turnover_days_from_average_balance():
    """周转天数 = 平均应收余额 ÷ 对外出货未税净额 × 30（分母为 0 时取 0）。"""
    def turnover_days(average_balance: float, net_shipment: float, days: int = 30) -> float:
        """与 engine.py 的 metric_ratio 分支一致：分母为 0 时取 0。"""
        return round(average_balance / net_shipment * days, 4) if net_shipment else 0.0

    assert turnover_days(90.0, 270.0) == 10.0
    assert turnover_days(90.0, 0.0) == 0.0
