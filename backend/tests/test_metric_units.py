"""指标单位解析规则测试（开放接口与文档共用）。"""

from app.modules.metric.units import DEFAULT_UNIT, resolve_metric_unit


def test_unit_prefers_declared_value():
    assert resolve_metric_unit("营销中心报价次数", {"unit": " 次 "}) == "次"
    assert resolve_metric_unit("任意名称", {"unit": "元"}) == "元"


def test_unit_from_ratio_scale():
    assert resolve_metric_unit("营销中心报价成功率", {"ratio_scale": 100}) == "%"
    assert resolve_metric_unit("营销中心应收周转天数", {"ratio_scale": 30}) == "天"


def test_unit_from_name_fallback():
    assert resolve_metric_unit("营销中心报价毛利率", None) == "%"
    assert resolve_metric_unit("营销中心制造成本率（材料及能源）", {}) == "%"
    assert resolve_metric_unit("营销中心下推周期（天）", None) == "天"
    assert resolve_metric_unit("营销中心批量下推周期", None) == "天"
    assert resolve_metric_unit("营销中心报价次数", {}) == "次"
    assert resolve_metric_unit("营销中心订单单数", {}) == "个"


def test_unit_default_is_amount():
    assert resolve_metric_unit("营销中心办公费用", {"kind": "account_balance_filter"}) == DEFAULT_UNIT
    assert resolve_metric_unit(None, None) == DEFAULT_UNIT
