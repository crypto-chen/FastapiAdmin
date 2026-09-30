"""指标单位解析：开放接口与文档生成共用一套规则，避免对外把「次数/比率」写成「元」。

优先级：
1. `measures["unit"]`：指标定义显式声明（推荐，新增指标时在 seed 脚本里写死）；
2. `measures["ratio_scale"]`：`100` → `%`（比率×100），`30` → `天`（按 30 天折算的周转天数）；
3. 指标名称兜底：`…率`→`%`、`…周期`/`…天数`→`天`、`…次数`→`次`；`…单数/数量/个数`→`个`；
4. 其余默认 `元`（金额类）。
"""

from typing import Any

DEFAULT_UNIT = "元"

_RATIO_SCALE_UNITS: dict[float, str] = {100: "%", 30: "天"}

# 名称关键字 → 单位。用「包含」而非「结尾」，因为指标名可能带括号后缀，
# 如「营销中心制造成本率（材料及能源）」「营销中心下推周期（天）」。
_NAME_KEYWORD_UNITS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("率", "占比", "百分比"), "%"),
    (("周期", "天数"), "天"),
    (("次数",), "次"),
    (("单数", "数量", "个数", "笔数"), "个"),
)


def resolve_metric_unit(name: str | None, measures: Any | None) -> str:
    """返回指标单位（对外展示与 open API `unit` 字段使用）。"""
    if isinstance(measures, dict):
        unit = measures.get("unit")
        if isinstance(unit, str) and unit.strip():
            return unit.strip()
        scale = measures.get("ratio_scale")
        if isinstance(scale, (int, float)) and not isinstance(scale, bool):
            mapped = _RATIO_SCALE_UNITS.get(float(scale))
            if mapped:
                return mapped

    text = (name or "").strip()
    for keywords, unit in _NAME_KEYWORD_UNITS:
        if any(keyword in text for keyword in keywords):
            return unit
    return DEFAULT_UNIT
