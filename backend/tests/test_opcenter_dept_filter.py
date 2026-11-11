"""运营中心主表指标：6601 部门编码过滤 + 17 项指标定义。"""

from app.modules.metric.engine import extract_account_balance
from scripts.seed_opcenter_metrics import (
    BASE_MEASURES,
    CATEGORY,
    DEPARTMENT_CODES,
    METRIC_DEFS,
)

FIELDS = ["FBALANCEID", "FDETAILNUMBER", "FDETAILNAME", "FDEBIT"]
BASE_CONFIG = {
    "account_field": "FBALANCEID",
    "account_prefix": "6601",
    "detail_code_field": "FDETAILNUMBER",
    "detail_name_field": "FDETAILNAME",
    "amount_field": "FDEBIT",
}


def _rows() -> list[list[str]]:
    return [
        ["6601", "", "", ""],
        ["", "BM000008/CI01", "在线营销部（改名后）/办公费", "100"],
        ["", "BM000021/CI01", "电商组/办公费", "200"],
        ["", "BM000023/CI01", "社媒组/办公费", "300"],
        ["", "BM000107/CI01", "官网/办公费", "400"],
        ["", "BM000999/CI01", "国内销售部/办公费", "999"],
        # 无部门前缀的汇总/明细行：配置部门过滤后必须排除
        ["", "GY.88", "内贸快递", "888"],
    ]


def test_department_filter_by_code_keeps_three_departments() -> None:
    config = {**BASE_CONFIG, "detail_name_contains": ["办公费"], "department_codes": DEPARTMENT_CODES}
    result = extract_account_balance(_rows(), FIELDS, config)

    assert result["total"] == 600.0
    assert result["matched_rows"] == 3
    assert set(result["departments"]) == {"BM000008", "BM000021", "BM000023"}


def test_department_filter_ignores_renamed_department() -> None:
    """名称改成新名字，编码不变时仍然计入。"""
    config = {**BASE_CONFIG, "detail_name_contains": ["办公费"], "department_codes": DEPARTMENT_CODES}
    rows = [
        ["6601", "", "", ""],
        ["", "BM000008/CI01", "运营中心一部/办公费", "123"],
    ]
    assert extract_account_balance(rows, FIELDS, config)["total"] == 123.0


def test_without_department_filter_keeps_previous_behavior() -> None:
    config = {**BASE_CONFIG, "detail_name_contains": ["办公费"]}
    assert extract_account_balance(_rows(), FIELDS, config)["total"] == 1999.0


def test_department_filter_excludes_rows_without_department_prefix() -> None:
    config = {**BASE_CONFIG, "detail_name_contains": ["快递"], "department_codes": DEPARTMENT_CODES}
    assert extract_account_balance(_rows(), FIELDS, config)["total"] == 0.0


def test_metric_definitions_cover_all_costs() -> None:
    codes = [item["code"] for item in METRIC_DEFS]
    assert codes == [f"OPC-COST-{index:02d}" for index in range(1, 18)]
    assert len(codes) == len(set(codes))

    by_code = {item["code"]: item for item in METRIC_DEFS}
    assert by_code["OPC-COST-01"]["detail_name_contains"] == ["办公费", "FLB辅/劳保"]
    assert by_code["OPC-COST-08"]["detail_name_contains"] == ["内贸快递"]
    assert "专用平台费用" not in by_code["OPC-COST-09"]["detail_name_contains"]
    assert by_code["OPC-COST-10"]["detail_name_contains"] == ["售后返工费", "售后运输费"]
    assert by_code["OPC-COST-11"]["detail_name_contains"] == ["电费"]
    assert by_code["OPC-COST-13"]["detail_name_contains"] == ["维修费"]
    assert all("detail_name_contains_by_period" not in item for item in METRIC_DEFS)
    assert all(item["detail_name_contains"] for item in METRIC_DEFS)
    assert BASE_MEASURES["department_codes"] == DEPARTMENT_CODES
    assert CATEGORY == "运营中心-主表指标"
    assert DEPARTMENT_CODES == ["BM000008", "BM000021", "BM000023"]
