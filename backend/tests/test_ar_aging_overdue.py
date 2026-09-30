"""「应收账款逾期应收」取数口径单元测试（纯函数，不依赖数据库与金蝶）。

口径：账龄 30 天以上（31 天及以上）的未收款汇总，按往来单位取净值、客户净额 ≤ 0 不计入。
实现是把账龄表的区间比例设成「30 天以内 0、30 天以上 100%」，再复用坏账计提执行器。
"""

from datetime import date, timedelta

from app.modules.metric.engine import extract_ar_aging_provision

FIELDS = [
    "FContactUnitNumber",
    "FCONTACTUNIT",
    "FBillNo",
    "FDate",
    "FEndDate",
    "FBalanceAmt",
]

AS_OF = date(2026, 9, 30)

# 与 scripts/seed_ar_aging_overdue_metric.py 的 BUCKETS / MEASURES 一致
CONFIG = {
    "kind": "ar_aging_provision",
    "netting": "customer",
    "amount_field": "FBalanceAmt",
    "customer_code_field": "FContactUnitNumber",
    "customer_name_field": "FCONTACTUNIT",
    "bill_no_field": "FBillNo",
    "date_field": "FEndDate",
    "fallback_date_field": "FDate",
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
    "buckets": [
        {"max_days": 30, "rate": 0.0},
        {"max_days": 60, "rate": 1.0},
        {"max_days": 90, "rate": 1.0},
        {"max_days": 180, "rate": 1.0},
        {"max_days": 365, "rate": 1.0},
        {"max_days": None, "rate": 1.0},
    ],
}


def _row(code, name, bill_no, days_ago, amount):
    """按「距今 N 天到期」造一行；到期日为空时引擎会退化取业务日期。"""
    end_date = (AS_OF - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return [code, name, bill_no, end_date, end_date, amount]


def test_only_overdue_part_is_summed():
    rows = [
        # 客户 A：40 天 1000（逾期）+ 10 天 500（未逾期）
        _row("200", "客户A", "BILL-1", 40, "1000"),
        _row("200", "客户A", "BILL-2", 10, "500"),
        # 客户 A 小计行（无单据编号）：必须跳过，否则重复计入
        _row("200", "客户A", "", 40, "1500"),
        # 客户 B：100 天 300（逾期）
        _row("300", "客户B", "BILL-3", 100, "300"),
        # 客户 D：恰好 30 天 700（不算逾期）+ 31 天 800（算逾期）
        _row("400", "客户D", "BILL-4", 30, "700"),
        _row("400", "客户D", "BILL-5", 31, "800"),
        # 内部客户 100：剔除
        _row("100", "内部客户", "BILL-6", 100, "999"),
    ]

    extracted = extract_ar_aging_provision(rows, FIELDS, CONFIG, AS_OF)

    assert extracted["total"] == 2100.0  # 1000（A）+ 300（B）+ 800（D）
    assert extracted["departments"]["200"]["value"] == 1000.0
    assert extracted["departments"]["300"]["value"] == 300.0
    assert extracted["departments"]["400"]["value"] == 800.0
    assert "100" not in extracted["departments"]


def test_customer_net_negative_is_excluded():
    rows = [
        # 客户 C：40 天 +300 与 5 天 -400 相抵后净额 -100 ≤ 0 → 整户不计入
        _row("500", "客户C", "BILL-7", 40, "300"),
        _row("500", "客户C", "BILL-8", 5, "-400"),
    ]

    extracted = extract_ar_aging_provision(rows, FIELDS, CONFIG, AS_OF)

    assert extracted["total"] == 0.0
    assert extracted["departments"] == {}
    assert extracted["excluded_customers"] == 1
