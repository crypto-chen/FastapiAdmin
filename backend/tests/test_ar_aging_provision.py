"""账龄计提取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

from datetime import date

from app.modules.metric.engine import (
    aging_bucket_label,
    aging_rate,
    extract_ar_aging_provision,
    period_end_date,
)

FIELDS = [
    "FContactUnitNumber",
    "FCONTACTUNIT",
    "FBillNo",
    "FDate",
    "FEndDate",
    "FBalanceAmt",
]
CONFIG = {
    "netting": "bill",
    "amount_field": "FBalanceAmt",
    "customer_code_field": "FContactUnitNumber",
    "customer_name_field": "FCONTACTUNIT",
    "bill_no_field": "FBillNo",
    "date_field": "FEndDate",
    "fallback_date_field": "FDate",
    "detail_code_exclude_in": [str(code) for code in range(100, 114)],
}

ROW_NETTING_CONFIG = {**CONFIG, "netting": "customer"}


def _row(code, name, bill_no, bill_date, end_date, amount):
    return [code, name, bill_no, bill_date, end_date, amount]


def test_period_end_date():
    assert period_end_date("month", "2026-09") == date(2026, 9, 30)
    assert period_end_date("month", "2026-02") == date(2026, 2, 28)
    assert period_end_date("day", "2026-09-28") == date(2026, 9, 28)
    assert period_end_date("year", "2026") == date(2026, 12, 31)


def test_aging_bucket_rule():
    buckets = [
        (30, 0.0),
        (60, 0.05),
        (90, 0.10),
        (180, 0.20),
        (365, 0.50),
        (None, 1.0),
    ]
    assert [aging_bucket_label(index, buckets) for index in range(len(buckets))] == [
        "0-30",
        "31-60",
        "61-90",
        "91-180",
        "181-365",
        ">365",
    ]
    assert aging_rate(0, buckets) == 0.0
    assert aging_rate(30, buckets) == 0.0
    assert aging_rate(31, buckets) == 0.05
    assert aging_rate(365, buckets) == 0.50
    assert aging_rate(366, buckets) == 1.0


def _sample_rows():
    return [
        # 0-30 天：0%
        _row("A001", "甲客户", "AR0001", "2026-09-10", "2026-09-10", "1,000.00"),
        # 31-60 天：5%
        _row("A001", "甲客户", "AR0002", "2026-08-01", "2026-08-01", "-2,000.00"),
        # 61-90 天：10%
        _row("A002", "乙客户", "AR0003", "2026-07-15", "2026-07-15", "3,000.00"),
        # 181-365 天：50%
        _row("A002", "乙客户", "AR0004", "2025-11-01", "2025-11-01", "4,000.00"),
        # 1 年以上：100%
        _row("A003", "丙客户", "AR0005", "2024-01-01", "2024-01-01", "5,000.00"),
        # 无到期日：退化为业务日期（>365 天）
        _row("A003", "丙客户", "AR0006", "2024-05-01", "", "600.00"),
        # 「小计」行必须跳过（金额是客户合计）
        _row("A001(小计)", "", "", "", "", "9,999.00"),
        # 内部客户必须剔除
        _row("101", "佛山永锢科技有限公司", "AR0007", "2024-01-01", "2024-01-01", "7,000.00"),
    ]


def test_extract_ar_aging_provision_by_bucket():
    """逐单口径：每张单据按自身账龄档位计提。"""
    result = extract_ar_aging_provision(_sample_rows(), FIELDS, CONFIG, as_of=date(2026, 9, 30))

    # 1,000×0 + (-2,000)×5% + 3,000×10% + 4,000×50% + 5,000×100% + 600×100%
    assert result["total"] == 7800.0
    assert result["amount_total"] == 11600.0
    assert result["matched_rows"] == 6
    assert result["buckets"]["0-30"]["amount"] == 1000.0
    assert result["buckets"]["31-60"]["provision"] == -100.0
    assert result["buckets"]["61-90"]["amount"] == 3000.0
    assert result["buckets"]["61-90"]["provision"] == 300.0
    assert result["buckets"][">365"]["amount"] == 5600.0
    assert result["buckets"][">365"]["provision"] == 5600.0
    assert result["departments"]["A001"]["value"] == -100.0
    assert result["departments"]["A002"]["value"] == 2300.0
    assert result["departments"]["A003"]["value"] == 5600.0
    assert result["departments"]["A001"]["name"] == "甲客户"
    assert result["as_of"] == "2026-09-30"


def test_extract_ar_aging_provision_customer_netting():
    """客户净值口径：客户净额 ≤ 0 整体不计提，净额为正的客户按档位净额计提。"""
    result = extract_ar_aging_provision(
        _sample_rows(), FIELDS, ROW_NETTING_CONFIG, as_of=date(2026, 9, 30)
    )

    # 甲客户净额 1,000-2,000 = -1,000 → 不计提
    assert "A001" not in result["departments"]
    assert result["excluded_customers"] == 1
    # 乙客户净额 7,000：3,000×10% + 4,000×50% = 2,300；丙客户 5,600：5,600×100%
    assert result["departments"]["A002"]["value"] == 2300.0
    assert result["departments"]["A003"]["value"] == 5600.0
    assert result["total"] == 7900.0
    assert result["amount_total"] == 12600.0
    assert result["matched_rows"] == 4
    assert result["buckets"]["31-60"]["amount"] == 0.0
    assert result["buckets"]["61-90"]["provision"] == 300.0
    assert result["netting"] == "customer"


def test_extract_ar_aging_provision_skip_negative():
    rows = [
        _row("A001", "甲客户", "AR0001", "2024-01-01", "2024-01-01", "1,000.00"),
        _row("A001", "甲客户", "AR0002", "2024-01-01", "2024-01-01", "-400.00"),
    ]
    result = extract_ar_aging_provision(
        rows, FIELDS, {**CONFIG, "skip_negative_amount": True}, as_of=date(2026, 9, 30)
    )
    assert result["total"] == 1000.0
    assert result["amount_total"] == 1000.0
    assert result["skipped_negative"] == 1
