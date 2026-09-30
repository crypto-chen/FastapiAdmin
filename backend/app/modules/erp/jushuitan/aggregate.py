"""销售出库单金额汇总：含税金额 → 未税金额。

两个现实约束（2026-08 实测数据）：

1. 聚水潭销售出库查询（docId=34）**不返回税额字段**，返回的都是含税口径金额，
   所以「未税总金额」按 ``含税金额 / (1 + 税率)`` 折算；税率不填（0）时未税=含税。
2. **单一口径必然漏数**：淘系/拼多多平台规则屏蔽价格字段，国内店铺单据的主表
   ``pay_amount`` 与明细 ``sale_amount`` 为空，只有明细 ``buyer_paid_amount``（买家实付）
   / ``seller_income_amount``（卖家实收）有值；跨境/自建站店铺反过来只有 ``sale_amount`` 有值。
   因此默认口径 ``items.auto`` = 明细行内按 ``先金额、再买家实付、后卖家实收`` 取第一个非零值。
"""

from __future__ import annotations

from typing import Any

# 取数口径 → (取值位置, 字段名)
AMOUNT_SOURCES: dict[str, tuple[str, str]] = {
    "order.pay_amount": ("order", "pay_amount"),
    "order.paid_amount": ("order", "paid_amount"),
    "order.buyer_paid_amount": ("order", "buyer_paid_amount"),
    "order.seller_income_amount": ("order", "seller_income_amount"),
    "items.sale_amount": ("items", "sale_amount"),
    "items.buyer_paid_amount": ("items", "buyer_paid_amount"),
    "items.seller_income_amount": ("items", "seller_income_amount"),
    "items.auto": ("items", "auto"),
}

# ``items.auto`` 的兜底顺序，可用 ``auto_fields`` 覆盖（例如把卖家实收提到最前）
AUTO_FALLBACK_FIELDS: tuple[str, ...] = ("sale_amount", "buyer_paid_amount", "seller_income_amount")


def parse_amount(value: Any) -> float:
    """金额字段兼容数字与带千分位/空值的字符串。"""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_untaxed(amount: float, tax_rate: float = 0.0, tax_inclusive: bool = True) -> float:
    """含税金额 → 未税金额。"""
    if not tax_inclusive:
        return float(amount)
    rate = float(tax_rate or 0)
    if rate <= 0:
        return float(amount)
    return float(amount) / (1 + rate / 100.0)


def resolve_amount_source(amount_source: str) -> tuple[str, str]:
    """口径字符串 → (取值位置, 字段名)，非法口径直接报错。"""
    source = AMOUNT_SOURCES.get(amount_source)
    if source is None:
        raise ValueError(f"不支持的取数口径: {amount_source}（可选：{', '.join(AMOUNT_SOURCES)}）")
    return source


def item_amount(item: dict, amount_source: str, auto_fields: list[str] | tuple[str, ...] | None = None) -> float:
    """取**单个明细行**金额；``items.auto`` 时按兜底顺序取第一个非零值。"""
    scope, field = resolve_amount_source(amount_source)
    if scope == "order":
        return 0.0
    if field != "auto":
        return parse_amount(item.get(field))
    for name in auto_fields or AUTO_FALLBACK_FIELDS:
        value = parse_amount(item.get(name))
        if value:
            return value
    return 0.0


def order_amount(row: dict, amount_source: str = "items.auto", auto_fields=None) -> float:
    """按口径取整单金额（明细口径对 items 求和）。"""
    scope, field = resolve_amount_source(amount_source)
    if scope == "order":
        return parse_amount(row.get(field))
    items = row.get("items")
    if not isinstance(items, list):
        return 0.0
    return float(sum(item_amount(item, amount_source, auto_fields) for item in items if isinstance(item, dict)))


def item_qty(row: dict) -> float:
    items = row.get("items")
    if not isinstance(items, list):
        return 0.0
    return float(sum(parse_amount(item.get("qty")) for item in items if isinstance(item, dict)))


def summarize(
    rows: list[dict],
    amount_source: str = "items.auto",
    tax_rate: float = 0.0,
    tax_inclusive: bool = True,
    by_shop: bool = False,
    auto_fields: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """汇总出库单行 → 单数、数量、含税金额、未税金额。

    参数:
    - rows (list[dict]): 销售出库查询返回的 ``datas`` 明细。
    - amount_source (str): 取数口径，见 :data:`AMOUNT_SOURCES`；默认 ``items.auto``。
    - tax_rate (float): 税率（百分比），0 表示接口金额即未税。
    - tax_inclusive (bool): 接口金额是否含税。
    - by_shop (bool): 是否按店铺拆分汇总。
    - auto_fields: ``items.auto`` 的兜底字段顺序。

    返回:
    - dict: ``order_count`` / ``item_qty`` / ``tax_inclusive_amount`` / ``untaxed_amount`` / ``by_shop``。
    """
    total_inclusive = 0.0
    total_qty = 0.0
    shops: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        amount = order_amount(row, amount_source, auto_fields)
        qty = item_qty(row)
        total_inclusive += amount
        total_qty += qty
        if by_shop:
            key = str(row.get("shop_id") if row.get("shop_id") is not None else "")
            bucket = shops.setdefault(
                key,
                {
                    "shop_id": row.get("shop_id"),
                    "shop_name": row.get("shop_name") or "",
                    "order_count": 0,
                    "item_qty": 0.0,
                    "tax_inclusive_amount": 0.0,
                    "untaxed_amount": 0.0,
                },
            )
            bucket["order_count"] = int(bucket["order_count"]) + 1
            bucket["item_qty"] = round(float(bucket["item_qty"]) + qty, 4)
            bucket["tax_inclusive_amount"] = round(float(bucket["tax_inclusive_amount"]) + amount, 4)
            bucket["untaxed_amount"] = round(float(bucket["untaxed_amount"]) + to_untaxed(amount, tax_rate, tax_inclusive), 4)

    return {
        "order_count": len([row for row in rows if isinstance(row, dict)]),
        "item_qty": round(total_qty, 4),
        "tax_inclusive_amount": round(total_inclusive, 4),
        "untaxed_amount": round(to_untaxed(total_inclusive, tax_rate, tax_inclusive), 4),
        "by_shop": shops,
    }
