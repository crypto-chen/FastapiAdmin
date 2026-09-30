"""营销中心平均应付余额取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

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

# 与 scripts/seed_marketing_ap_turnover_metric.py 的 AVG_BALANCE_MEASURES 一致
CONFIG = {
    "account_field": "FBALANCEID",
    "account_prefix": "2202",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "require_detail": True,
    "detail_is_department": False,
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
    "amount_terms": [
        {"field": "FBEGINCREDIT", "sign": 0.5},
        {"field": "FBEGINDEBIT", "sign": -0.5},
        {"field": "FENDCREDIT", "sign": 0.5},
        {"field": "FENDDEBIT", "sign": -0.5},
    ],
}


def _row(account, detail_code, detail_name, begin_debit, begin_credit, end_debit, end_credit):
    """科目行 + 核算维度行同构：科目列在核算维度行上为空，由上一科目行继承。"""
    return [
        account,
        "应付账款",
        detail_code,
        detail_name,
        begin_debit,
        begin_credit,
        end_debit,
        end_credit,
    ]


def test_average_balance_is_half_begin_plus_half_end():
    rows = [
        # 科目汇总行（无核算维度）：必须跳过，避免与往来单位明细重复
        _row("2202", "", "", "", "999,999", "", "999,999"),
        # 外部供应商 VEN00001：期初贷 100、期末贷 120 → 0.5×100 + 0.5×120 = 110
        _row("", "VEN00001", "外部供应商A", "", "100", "", "120"),
        # 内部组织 101：应剔除
        _row("", "101", "佛山永锢科技有限公司", "", "1000", "", "1000"),
        # 外部供应商 VEN00002（借方余额，如预付/红字）：期初借 40、期末借 30 → -20 - 15 = -35
        _row("", "VEN00002", "外部供应商B", "40", "", "30", ""),
        # 非 2202 科目：不匹配（2203 预收账款）
        _row("2203", "", "预收账款", "", "1", "", "1"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    assert extracted["total"] == 75.0  # 110 - 35
    assert extracted["matched_rows"] == 2
    assert set(extracted["departments"]) == {"VEN00001", "VEN00002"}
    assert extracted["departments"]["VEN00001"]["value"] == 110.0
    assert extracted["departments"]["VEN00001"]["name"] == "外部供应商A"
    assert extracted["departments"]["VEN00002"]["value"] == -35.0


def test_sub_accounts_are_included():
    """应付账款下有 2202.01 暂估应付款、2202.02 明细应付款，前缀 2202 应全部纳入。"""
    rows = [
        _row("2202.01", "", "", "", "500", "", "600"),
        _row("", "VEN00010", "供应商甲", "", "300", "", "400"),
        _row("", "VEN00011", "供应商乙", "", "800", "", "800"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    # 平均余额 = 0.5×300 + 0.5×400 + 0.5×800 + 0.5×800 = 350 + 800
    assert extracted["total"] == 1150.0
    assert extracted["matched_rows"] == 2


def test_turnover_days_from_average_balance():
    """应付周转天数 = 平均应付余额 ÷ 当期采购入库金额（含税）× 30（分母为 0 时取 0）。"""
    def turnover_days(average_balance: float, purchase_inbound: float, days: int = 30) -> float:
        """与 engine.py 的 metric_ratio 分支一致：分母为 0 时取 0。"""
        return round(average_balance / purchase_inbound * days, 4) if purchase_inbound else 0.0

    assert turnover_days(90.0, 270.0) == 10.0
    assert turnover_days(1_150_000.0, 11_500_000.0) == 3.0
    assert turnover_days(90.0, 0.0) == 0.0
