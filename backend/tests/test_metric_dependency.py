"""指标依赖提取与分层调度测试（纯函数，不依赖数据库与外部接口）。"""

from datetime import UTC, datetime

from app.modules.metric.batch import build_metric_layers
from app.modules.metric.engine import local_day_start, metric_dependency_codes


def _metric(mid: int, code: str, measures: dict) -> dict:
    return {"id": mid, "code": code, "name": code, "period_type": "month", "measures": measures}


# --------------------------------------------------------------------------- #
# metric_dependency_codes：依赖字段的解析口径
# --------------------------------------------------------------------------- #
def test_sum_and_scale_use_component_codes():
    assert metric_dependency_codes({"kind": "metric_sum", "component_metric_codes": ["a", "b"]}) == ["a", "b"]
    # 单字符串等价于单元素列表（配置里手写一个编码是常见写法）
    assert metric_dependency_codes({"kind": "metric_scale", "component_metric_codes": "a"}) == ["a"]


def test_ratio_collects_numerator_denominator_and_subtrahends():
    codes = metric_dependency_codes(
        {
            "kind": "metric_ratio",
            "numerator_metric_codes": ["n1"],
            "numerator_subtrahend_metric_codes": ["n2"],
            "denominator_metric_codes": ["d1"],
            "denominator_subtrahend_metric_codes": ["d2"],
        }
    )
    assert codes == ["n1", "n2", "d1", "d2"]


def test_diff_dedupes_codes_used_on_both_sides():
    codes = metric_dependency_codes(
        {"kind": "metric_diff", "addend_metric_codes": ["a", "b"], "subtrahend_metric_codes": ["b"]}
    )
    assert codes == ["a", "b"]


def test_non_derived_kind_has_no_dependency():
    assert metric_dependency_codes({"kind": "account_balance_filter", "account_prefix": "6401"}) == []
    assert metric_dependency_codes(None) == []


def test_blank_codes_are_dropped():
    assert metric_dependency_codes({"kind": "metric_sum", "component_metric_codes": [" a ", "", "b"]}) == ["a", "b"]


# --------------------------------------------------------------------------- #
# build_metric_layers：分层顺序、并发同层、配置问题
# --------------------------------------------------------------------------- #
def test_dependencies_are_ordered_before_dependents():
    metrics = [
        _metric(1, "a", {"kind": "account_balance_filter"}),
        _metric(2, "b", {"kind": "metric_sum", "component_metric_codes": ["a"]}),
        _metric(
            3,
            "c",
            {"kind": "metric_ratio", "numerator_metric_codes": ["b"], "denominator_metric_codes": ["a"]},
        ),
    ]
    layers, problems = build_metric_layers(metrics)
    assert problems == []
    assert [[item["code"] for item in layer] for layer in layers] == [["a"], ["b"], ["c"]]


def test_independent_metrics_share_one_layer():
    metrics = [
        _metric(1, "a", {"kind": "account_balance_filter"}),
        _metric(2, "b", {"kind": "account_balance_filter"}),
        _metric(3, "c", {"kind": "metric_sum", "component_metric_codes": ["a", "b"]}),
    ]
    layers, problems = build_metric_layers(metrics)
    assert problems == []
    # 同层按 id 升序，保证每天执行顺序稳定
    assert [[item["code"] for item in layer] for layer in layers] == [["a", "b"], ["c"]]


def test_missing_dependency_is_reported_but_not_blocking():
    metrics = [_metric(1, "c", {"kind": "metric_sum", "component_metric_codes": ["ghost"]})]
    layers, problems = build_metric_layers(metrics)
    assert [[item["code"] for item in layer] for layer in layers] == [["c"]]
    assert len(problems) == 1 and "ghost" in problems[0]


def test_self_dependency_is_dropped():
    metrics = [_metric(1, "a", {"kind": "metric_sum", "component_metric_codes": ["a"]})]
    layers, problems = build_metric_layers(metrics)
    assert [[item["code"] for item in layer] for layer in layers] == [["a"]]
    assert any("依赖自身" in problem for problem in problems)


def test_cycle_falls_back_to_single_layer_with_problem():
    metrics = [
        _metric(1, "a", {"kind": "metric_sum", "component_metric_codes": ["b"]}),
        _metric(2, "b", {"kind": "metric_sum", "component_metric_codes": ["a"]}),
    ]
    layers, problems = build_metric_layers(metrics)
    assert [[item["code"] for item in layer] for layer in layers] == [["a", "b"]]
    assert any("环" in problem for problem in problems)


# --------------------------------------------------------------------------- #
# local_day_start：新鲜度判定线取 Asia/Shanghai 当天 00:00 对应的 UTC 时刻
# --------------------------------------------------------------------------- #
def test_local_day_start_uses_shanghai_midnight():
    # 2026-09-30 01:00 UTC = 上海 09:00 → 当天起点 = 上海 09-30 00:00 = UTC 09-29 16:00
    assert local_day_start(datetime(2026, 9, 30, 1, 0, tzinfo=UTC)) == datetime(2026, 9, 29, 16, 0, tzinfo=UTC)
    # 跨过上海午夜：2026-09-29 20:00 UTC = 上海 09-30 04:00，同属 09-30 这一天
    assert local_day_start(datetime(2026, 9, 29, 20, 0, tzinfo=UTC)) == datetime(2026, 9, 29, 16, 0, tzinfo=UTC)
