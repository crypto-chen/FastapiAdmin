"""营销中心应付余额取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

from app.modules.metric.engine import extract_account_balance

FIELDS = [
    "FBALANCEID",
    "FBALANCENAME",
    "FDETAILNUMBER",
    "FDETAILNAME",
    "FENDDEBIT",
    "FENDCREDIT",
]

# 与 scripts/seed_marketing_metrics.py 里 marketing_ap_balance 的 measures 一致
CONFIG = {
    "account_field": "FBALANCEID",
    "account_prefix": "2202",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "require_detail": True,
    "detail_is_department": False,
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
    "amount_terms": [
        {"field": "FENDCREDIT", "sign": 1},
        {"field": "FENDDEBIT", "sign": -1},
    ],
}


def _row(account, detail_code, detail_name, end_debit, end_credit):
    """科目行 + 核算维度行同构：科目列在核算维度行上为空，由上一科目行继承。"""
    return [account, "应付账款", detail_code, detail_name, end_debit, end_credit]


def test_credit_balance_of_external_suppliers():
    rows = [
        # 科目汇总行（无核算维度）：必须跳过，避免与明细重复
        _row("2202", "", "", "1,142,435.51", ""),
        # 下级科目汇总行（无核算维度）：同样跳过
        _row("2202.01", "", "", "", "6,471,964.05"),
        # 外部供应商 VEN00001：期末贷 100 → 贷方余额 +100
        _row("", "VEN00001", "外部供应商A", "", "100"),
        # 内部组织 101：应剔除
        _row("", "101", "佛山永锢科技有限公司", "", "1000"),
        # 外部供应商 VEN00002（借方余额，如预付/红字）：期末借 30 → 贷方余额 -30
        _row("", "VEN00002", "外部供应商B", "30", ""),
        # 非 2202 科目：不匹配（2203 预收账款）
        _row("2203", "", "预收账款", "", "999"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    assert extracted["total"] == 70.0  # 100 - 30
    assert extracted["matched_rows"] == 2
    assert set(extracted["departments"]) == {"VEN00001", "VEN00002"}
    assert extracted["departments"]["VEN00001"]["value"] == 100.0
    assert extracted["departments"]["VEN00001"]["name"] == "外部供应商A"
    assert extracted["departments"]["VEN00002"]["value"] == -30.0


def test_sub_accounts_are_included():
    """应付账款下有 2202.01 暂估应付款、2202.02 明细应付款，前缀 2202 应全部纳入。"""
    rows = [
        _row("2202.01", "", "", "", "500"),
        _row("", "VEN00010", "供应商甲", "", "300"),
        _row("2202.02", "", "", "", "800"),
        _row("", "VEN00011", "供应商乙", "", "800"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    assert extracted["total"] == 1100.0
    assert extracted["matched_rows"] == 2
