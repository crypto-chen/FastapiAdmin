"""营销中心费用口径：软件费用、平台固定费、2026-10 售后运输费重分类。"""

from app.modules.metric.engine import extract_account_balance
from scripts.seed_marketing_metrics import METRIC_DEFS

FIELDS = ["FBALANCEID", "FDETAILNUMBER", "FDETAILNAME", "FDEBIT"]
BASE_CONFIG = {
    "account_field": "FBALANCEID",
    "account_prefix": "6601",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "amount_field": "FDEBIT",
}


def _rows() -> list[list[str]]:
    """科目行 + 三条核算维度行：内贸快递 100、售后运输费 200、售后其它费用 50。"""
    return [
        ["6601", "", "", ""],
        ["", "BM000001/CI011", "营销部/内贸快递", "100"],
        ["", "BM000001/CI012", "营销部/售后运输费", "200"],
        ["", "BM000001/CI013", "营销部/售后其它费用", "50"],
    ]


DOMESTIC_CONFIG = {
    **BASE_CONFIG,
    "detail_name_contains": ["内贸快递", "售后运输费"],
    "detail_name_contains_by_period": {"2026-10": ["内贸快递"]},
}

AFTER_SALES_CONFIG = {
    **BASE_CONFIG,
    "detail_name_contains": ["售后其它费用", "售后赔偿费", "售后返工费"],
    "detail_name_contains_by_period": {
        "2026-10": ["售后其它费用", "售后赔偿费", "售后返工费", "售后运输费"],
    },
}


def test_domestic_express_excludes_after_sales_transport_only_in_2026_10() -> None:
    assert extract_account_balance(_rows(), FIELDS, DOMESTIC_CONFIG)["total"] == 300.0
    assert extract_account_balance(_rows(), FIELDS, DOMESTIC_CONFIG, period="2026-09")["total"] == 300.0
    assert extract_account_balance(_rows(), FIELDS, DOMESTIC_CONFIG, period="2026-10")["total"] == 100.0
    assert extract_account_balance(_rows(), FIELDS, DOMESTIC_CONFIG, period="2026-11")["total"] == 300.0


def test_after_sales_expense_includes_after_sales_transport_only_in_2026_10() -> None:
    assert extract_account_balance(_rows(), FIELDS, AFTER_SALES_CONFIG)["total"] == 50.0
    assert extract_account_balance(_rows(), FIELDS, AFTER_SALES_CONFIG, period="2026-09")["total"] == 50.0
    assert extract_account_balance(_rows(), FIELDS, AFTER_SALES_CONFIG, period="2026-10")["total"] == 250.0
    assert extract_account_balance(_rows(), FIELDS, AFTER_SALES_CONFIG, period="2026-11")["total"] == 50.0


def test_metric_definitions_cover_new_and_changed_calibers() -> None:
    by_code = {item["code"]: item for item in METRIC_DEFS}

    assert by_code["marketing_software_expense"]["name"] == "营销中心软件费用"
    assert by_code["marketing_software_expense"]["detail_name_contains"] == ["软件费用"]
    assert "平台固定费" in by_code["marketing_platform_expense"]["detail_name_contains"]
    assert by_code["marketing_domestic_express_expense"]["detail_name_contains_by_period"] == {
        "2026-10": ["内贸快递"]
    }
    assert by_code["marketing_after_sales_expense"]["detail_name_contains_by_period"] == {
        "2026-10": ["售后其它费用", "售后赔偿费", "售后返工费", "售后运输费"]
    }
    components = by_code["marketing_total_expense"]["measures"]["component_metric_codes"]
    assert "marketing_software_expense" in components
    assert len(components) == len(set(components))
