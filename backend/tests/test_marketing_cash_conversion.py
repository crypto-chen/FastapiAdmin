"""营销中心现金转换周期指标定义与计算口径单元测试（纯函数，不依赖数据库）。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import importlib.util  # noqa: E402

from app.modules.metric.engine import METRIC_DIFF_KIND, SUPPORTED_KINDS  # noqa: E402
from app.modules.metric.units import resolve_metric_unit  # noqa: E402


def _load_seed_module():
    path = PROJECT_ROOT / "scripts" / "seed_marketing_cash_conversion_metric.py"
    spec = importlib.util.spec_from_file_location("seed_marketing_cash_conversion_metric", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measures_are_supported_metric_diff():
    module = _load_seed_module()

    assert METRIC_DIFF_KIND in SUPPORTED_KINDS
    assert module.MEASURES["kind"] == METRIC_DIFF_KIND
    # 加项：库存周转天数 + 应收周转天数；减项：应付周转天数
    assert module.MEASURES["addend_metric_codes"] == [
        "marketing_inventory_turnover_days",
        "marketing_ar_turnover_days",
    ]
    assert module.MEASURES["subtrahend_metric_codes"] == ["marketing_ap_turnover_days"]
    assert module.MEASURES["unit"] == "天"


def test_unit_is_days():
    module = _load_seed_module()
    assert resolve_metric_unit(module.METRIC_NAME, module.MEASURES) == "天"


def test_cycle_is_inventory_plus_receivable_minus_payable():
    """与 engine.py 的 metric_diff 分支一致：加项合计 − 减项合计，保留 4 位小数。"""
    def cash_conversion_cycle(inventory_days: float, ar_days: float, ap_days: float) -> float:
        return round(inventory_days + ar_days - ap_days, 4)

    assert cash_conversion_cycle(4.3327, -20.98, 12.5) == -29.1473
    assert cash_conversion_cycle(30.0, 60.0, 45.0) == 45.0
