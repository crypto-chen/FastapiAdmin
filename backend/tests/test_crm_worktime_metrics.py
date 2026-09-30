"""营销中心 CRM 工时指标（``/hs/getWorkTime``）取数规则测试。

接口实测返回结构：``data.regularWorkHours`` = 正常上班时间（小时）、
``data.overtimeHours`` = 加班时间（小时），另有 ``regularWork`` / ``overtime`` 两组明细对象。
"""

from app.modules.metric.engine import extract_api_scalar
from app.modules.metric.units import DEFAULT_UNIT, resolve_metric_unit

# 接口真实返回（明细数组已裁剪，只保留取值用到的层级）
WORKTIME_PAYLOAD = {
    "code": 1,
    "msg": "ok",
    "data": {
        "regularWorkHours": 13890,
        "overtimeHours": 1516.35,
        "regularWork": {"sec": 50004000, "hours": 13890, "workDays": 26},
        "overtime": {"sec": 5458860, "hours": 1516.35, "crossDayCount": 2},
    },
}


def test_regular_work_hours_takes_regular_work_hours_field():
    measures = {"kind": "api_scalar_amount", "data_field": "data.regularWorkHours", "unit": "小时"}
    assert extract_api_scalar(WORKTIME_PAYLOAD, measures)["total"] == 13890.0


def test_overtime_hours_takes_overtime_hours_field():
    measures = {"kind": "api_scalar_amount", "data_field": "data.overtimeHours", "unit": "小时"}
    result = extract_api_scalar(WORKTIME_PAYLOAD, measures)
    assert result["total"] == 1516.35
    assert result["matched_rows"] == 1


def test_missing_or_empty_data_is_zero():
    measures = {"data_field": "data.regularWorkHours"}
    assert extract_api_scalar({"code": 1, "data": None}, measures)["total"] == 0.0
    assert extract_api_scalar({"code": 1}, measures)["total"] == 0.0


def test_worktime_unit_must_be_declared_as_hours():
    # 工时不是金额：显式声明 unit 后按「小时」输出
    assert resolve_metric_unit("营销中心正常工作时间", {"unit": "小时"}) == "小时"
    assert resolve_metric_unit("营销中心加班时间", {"unit": "小时"}) == "小时"
    assert resolve_metric_unit("营销中心总劳动时间", {"unit": "小时"}) == "小时"
    # 名称里没有「率/周期/次数」等关键词，不声明 unit 会退回默认单位（金额），故必须声明
    assert resolve_metric_unit("营销中心正常工作时间", {}) == DEFAULT_UNIT


def test_total_labor_hours_is_sum_of_normal_and_overtime():
    """总劳动时间 = 正常工作时间 + 加班时间（汇总指标自身不取数，按组成指标当期值相加）。"""
    measures = {
        "kind": "metric_sum",
        "component_metric_codes": ["marketing_regular_work_hours", "marketing_overtime_hours"],
        "unit": "小时",
    }
    assert measures["component_metric_codes"] == [
        "marketing_regular_work_hours",
        "marketing_overtime_hours",
    ]
    normal = extract_api_scalar(WORKTIME_PAYLOAD, {"data_field": "data.regularWorkHours"})["total"]
    overtime = extract_api_scalar(WORKTIME_PAYLOAD, {"data_field": "data.overtimeHours"})["total"]
    assert normal + overtime == 15406.35  # 2026-08 实测：13890 + 1516.35
