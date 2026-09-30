"""营销中心销售成本取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

from app.modules.metric.engine import extract_account_balance

FIELDS = [
    "FBALANCEID",
    "FBALANCENAME",
    "FDETAILNUMBER",
    "FDETAILNAME",
    "FBEGINDEBIT",
    "FBEGINCREDIT",
    "FDEBIT",
]

# 与 scripts/seed_marketing_sales_cost_metric.py 的 MEASURES 一致
# （org_codes 在引擎装载同步任务时生效，不参与本纯函数）
CONFIG = {
    "account_field": "FBALANCEID",
    "account_prefix": "6401",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "amount_field": "FDEBIT",
    "require_detail": True,
    "detail_is_department": False,
}


def _row(account, account_name, detail_code, detail_name, debit):
    """科目行 + 核算维度行同构：科目列在核算维度行上为空，由上一科目行继承。"""
    return [account, account_name, detail_code, detail_name, "", "", debit]


def test_account_summary_rows_are_skipped():
    rows = [
        # 科目汇总行（无核算维度）：必须跳过
        _row("6401", "主营业务成本", "", "", "1,000.00"),
        _row("6401.01", "主营业务成本-内销成本", "", "", "600.00"),
        # 下级科目 6401.01 的客户明细：100 + 200 = 300
        _row("", "", "C001", "客户A", "100.00"),
        _row("", "", "C002", "客户B", "200.00"),
        # 下级科目 6401.03 的客户明细
        _row("6401.03", "主营业务成本-集团内", "", "", "400.00"),
        _row("", "", "C003", "集团内客户", "400.00"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    # 只累加明细行：100 + 200 + 400 = 700（不含科目汇总行的 1000 + 600 + 400）
    assert extracted["total"] == 700.0
    assert extracted["matched_rows"] == 3
    assert extracted["departments"]["C001"]["value"] == 100.0
    assert extracted["departments"]["C003"]["name"] == "集团内客户"


def test_other_accounts_are_excluded():
    rows = [
        _row("6401", "主营业务成本", "", "", "300.00"),
        _row("", "", "C001", "客户A", "300.00"),
        # 非 6401 科目：不匹配
        _row("6403", "税金及附加", "", "", "50.00"),
        _row("", "", "C009", "客户X", "50.00"),
        _row("1122", "应收账款", "", "", "999.00"),
        _row("", "", "C010", "客户Y", "999.00"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    assert extracted["total"] == 300.0
    assert extracted["matched_rows"] == 1


def test_red_letter_negative_amounts_are_included():
    rows = [
        _row("6401", "主营业务成本", "", "", "80.00"),
        _row("", "", "C001", "客户A", "100.00"),
        # 红字冲销：负数一并合计
        _row("", "", "C002", "客户B", "-20.00"),
    ]

    extracted = extract_account_balance(rows, FIELDS, CONFIG)

    assert extracted["total"] == 80.0
    assert extracted["matched_rows"] == 2
