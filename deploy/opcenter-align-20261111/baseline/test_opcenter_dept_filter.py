"""运营中心主表指标：6601 部门过滤 + 17 项指标定义。"""

from app.modules.metric.engine import extract_account_balance
from scripts.seed_opcenter_metrics import CATEGORY, DEPARTMENTS, METRIC_DEFS

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
        ["", "BM01/CI01", "在线营销部/办公费", "100"],
        ["", "BM02/CI01", "社媒组/办公费", "200"],
        ["", "BM03/CI01", "电商组/办公费", "300"],
        ["", "BM04/CI01", "官网/办公费", "400"],
        ["", "BM05/CI01", "国内销售部/办公费", "999"],
        # 无部门前缀的汇总/明细行：配置部门过滤后必须排除
        ["", "GY.88", "内贸快递", "888"],
    ]


def test_department_filter_keeps_only_four_departments() -> None:
    config = {**BASE_CONFIG, "detail_name_contains": ["办公费"], "department_names": DEPARTMENTS}
    result = extract_account_balance(_rows(), FIELDS, config)

    assert result["total"] == 1000.0
    assert result["matched_rows"] == 4
    assert set(result["departments"]) == {"BM01", "BM02", "BM03", "BM04"}


def test_without_department_filter_keeps_previous_behavior() -> None:
    config = {**BASE_CONFIG, "detail_name_contains": ["办公费"]}
    assert extract_account_balance(_rows(), FIELDS, config)["total"] == 1999.0


def test_department_filter_excludes_rows_without_department_prefix() -> None:
    config = {**BASE_CONFIG, "detail_name_contains": ["快递"], "department_names": DEPARTMENTS}
    assert extract_account_balance(_rows(), FIELDS, config)["total"] == 0.0


def test_metric_definitions_cover_all_costs() -> None:
    codes = [item["code"] for item in METRIC_DEFS]
    assert codes == [f"OPC-COST-{index:02d}" for index in range(1, 18)]
    assert len(codes) == len(set(codes))

    by_code = {item["code"]: item for item in METRIC_DEFS}
    assert by_code["OPC-COST-01"]["name"] == "运营中心办公费"
    assert by_code["OPC-COST-09"]["detail_name_contains"][-1] == "平台固定费"
    assert by_code["OPC-COST-13"]["detail_name_exclude"] == ["车辆维修费"]
    assert all(item["detail_name_contains"] for item in METRIC_DEFS)
    assert CATEGORY == "运营中心-主表指标"
    assert DEPARTMENTS == ["在线营销部", "社媒组", "电商组", "官网"]
