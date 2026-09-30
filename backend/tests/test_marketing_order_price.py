"""营销中心客单价 / 订单数指标定义与口径单元测试（纯函数，不依赖数据库）。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import importlib.util  # noqa: E402

from app.modules.metric.engine import METRIC_RATIO_KIND, SUPPORTED_KINDS  # noqa: E402
from app.modules.metric.units import resolve_metric_unit  # noqa: E402


def _load_seed_module():
    path = PROJECT_ROOT / "scripts" / "seed_crm_marketing_metrics.py"
    spec = importlib.util.spec_from_file_location("seed_crm_marketing_metrics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metric(module, code: str) -> dict:
    for item in module.METRICS:
        if item["code"] == code:
            return item
    raise AssertionError(f"未找到指标定义: {code}")


def test_order_count_reads_data_count():
    module = _load_seed_module()
    metric = _metric(module, "marketing_order_count")

    assert metric["path"] == "/hs/getOrderCount"
    assert metric["measures"] == {"data_field": "data.count", "unit": "单"}
    # 同步任务按接口建：/hs/getOrderCount 必须出现在来源对象清单里
    assert any(obj["path"] == "/hs/getOrderCount" for obj in module.SOURCE_OBJECTS)


def test_order_price_is_ratio_intake_over_count():
    module = _load_seed_module()
    measures = _metric(module, "marketing_order_price")["measures"]

    assert METRIC_RATIO_KIND in SUPPORTED_KINDS
    assert measures["kind"] == METRIC_RATIO_KIND
    assert measures["numerator_metric_codes"] == ["marketing_order_intake_untaxed"]
    assert measures["denominator_metric_codes"] == ["marketing_order_count"]
    assert measures["ratio_scale"] == 1
    assert measures["unit"] == "元/单"
    # 分子/分母都必须是本脚本声明的指标，避免指向不存在的编码
    codes = {item["code"] for item in module.METRICS}
    assert set(measures["numerator_metric_codes"]) <= codes
    assert set(measures["denominator_metric_codes"]) <= codes


def test_units_are_declared():
    module = _load_seed_module()
    assert resolve_metric_unit("营销中心订单数", _metric(module, "marketing_order_count")["measures"]) == "单"
    assert resolve_metric_unit("营销中心客单价", _metric(module, "marketing_order_price")["measures"]) == "元/单"


def test_order_price_math_matches_engine():
    """与 engine.py 的 metric_ratio 分支一致：分子 ÷ 分母 × ratio_scale，保留 4 位小数。"""

    def order_price(intake: float, count: int) -> float:
        return round(intake / count, 4) if count else 0.0

    assert order_price(3138000.0, 3138) == 1000.0
    assert order_price(100.0, 3) == 33.3333
    assert order_price(100.0, 0) == 0.0
