"""平台分析取数：从零售订单/售后/店铺主数据实时汇总，不落宽表。

输出按 ``PLT-xx`` 字段编码组织，前端与产品线分析一样按字段编码渲染列。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.retail.model import RetailOrderModel, RetailShopModel
from app.modules.retail.query_service import (
    RetailQueryService,
    hq_allocation_rate,
    retail_tax_rate,
    settlement_rate,
)

from .fields import PLATFORM_FIELDS
from .schema import PlatformAnalysisQueryParam

# 需要求和的金额/数量字段（比率字段由分子分母重算）
SUM_FIELDS = (
    "PLT-04",
    "PLT-05",
    "PLT-06",
    "PLT-08",
    "PLT-09",
    "PLT-10",
    "PLT-11",
    "PLT-12",
    "PLT-13",
    "PLT-23",
)
NUMERIC_FIELDS = {item["field_code"] for item in PLATFORM_FIELDS if item["data_type"] in {"number", "percent"}}

PLATFORM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("天猫", ("天猫", "淘宝")),
    ("京东", ("京东",)),
    ("拼多多", ("拼多多", "多多")),
    ("抖音", ("抖音", "抖店")),
    ("小红书", ("小红书",)),
    ("1688", ("1688", "阿里巴巴")),
)


def normalize_platform(raw: str | None) -> str:
    """把 ``retail_shop.shop_site`` 归一成平台大类。"""
    text = (raw or "").strip()
    if not text:
        return "其他"
    for name, keywords in PLATFORM_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return name
    return "其他"


def _rate(return_abs: float, net: float, shipment: float) -> float:
    base = net if net > 0 else shipment
    return round(return_abs / base, 4) if base else 0.0


def _row(
    *,
    period: str,
    platform: str,
    shop_name: str,
    shop_id: int | str,
    order_count: int,
    shipped_count: int,
    cancelled_count: int,
    intake: float,
    shipment: float,
    cancelled: float,
    refund: float,
    level: str,
    row_id: str,
) -> dict[str, Any]:
    # PLT-11 退货退款 = 取消单 + 发货后售后（两者都为负数）
    return_total = round(cancelled + refund, 2)
    return_abs = abs(return_total)
    net = round(shipment + return_total, 2)
    settlement = round(net * settlement_rate() / 100, 2)
    # 总部分摊 PLT-23 = 营销结算收入 PLT-13 × 4%（符号与 PLT-13 一致；结算收益里按 -PLT-23 扣减）
    hq_allocation = round(settlement * hq_allocation_rate() / 100, 2)
    # 客单价 PLT-38 = 接单未税 ÷ 有效订单数（剔除取消单）
    valid_orders = max(order_count - cancelled_count, 0)
    avg_order_value = round(intake / valid_orders, 2) if valid_orders else 0.0
    return {
        "id": row_id,
        "is_aggregate": {"detail": 0, "platform": 1, "total": 2}.get(level, 0),
        "aggregate_level": level,
        "period_value": period,
        "PLT-00": period,
        "PLT-01": platform,
        "PLT-02": shop_name,
        "PLT-03": shop_id,
        "PLT-04": order_count,
        "PLT-05": shipped_count,
        "PLT-06": cancelled_count,
        "PLT-08": round(intake, 2),
        "PLT-09": round(shipment, 2),
        "PLT-10": round(cancelled, 2),
        "PLT-11": return_total,
        "PLT-12": net,
        "PLT-13": settlement,
        "PLT-23": hq_allocation,
        "PLT-37": _rate(return_abs, net, shipment),
        "PLT-38": avg_order_value,
    }


class PlatformAnalysisService:
    """平台分析（指标中心 → 平台分析）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fields(self) -> list[dict[str, Any]]:
        return PLATFORM_FIELDS

    async def periods(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(RetailOrderModel.period_value)
                .where(RetailOrderModel.is_deleted == False)  # noqa: E712
                .distinct()
                .order_by(RetailOrderModel.period_value.desc())
                .limit(36)
            )
        ).scalars().all()
        return [str(item) for item in rows if item]

    async def platform_options(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(RetailShopModel.shop_site)
                .where(RetailShopModel.is_deleted == False)  # noqa: E712
                .distinct()
            )
        ).scalars().all()
        return sorted({normalize_platform(item) for item in rows})

    async def _shop_map(self) -> dict[int, dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    RetailShopModel.shop_id,
                    RetailShopModel.shop_name,
                    RetailShopModel.shop_site,
                ).where(RetailShopModel.is_deleted == False)  # noqa: E712
            )
        ).all()
        return {
            int(row[0]): {"shop_name": row[1], "shop_site": row[2]}
            for row in rows
        }

    async def _detail_rows(self, period_value: str | None) -> list[dict[str, Any]]:
        data = await RetailQueryService(self.db).analysis_summary(period_value)
        shop_map = await self._shop_map()
        rows: list[dict[str, Any]] = []
        for item in data.get("items") or []:
            shop_id = int(item["shop_id"])
            shop = shop_map.get(shop_id, {})
            platform = normalize_platform(shop.get("shop_site"))
            shop_name = item.get("shop_name") or shop.get("shop_name") or f"店铺{shop_id}"
            rows.append(
                _row(
                    period=item["period_value"],
                    platform=platform,
                    shop_name=shop_name,
                    shop_id=shop_id,
                    order_count=int(item["order_count"]),
                    shipped_count=int(item["shipped_order_count"]),
                    cancelled_count=int(item["cancelled_order_count"]),
                    intake=float(item["intake_untaxed"]),
                    shipment=float(item["shipment_untaxed"]),
                    cancelled=float(item["cancelled_untaxed"]),
                    refund=float(item["refund_untaxed"]),
                    level="detail",
                    row_id=f"detail-{item['period_value']}-{shop_id}",
                )
            )
        return rows

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["PLT-00"], row["PLT-01"] if level == "platform" else "全部")
            bucket = buckets.get(key)
            if bucket is None:
                bucket = dict.fromkeys(SUM_FIELDS, 0)
                bucket["PLT-00"] = row["PLT-00"]
                bucket["PLT-01"] = "全部" if level == "total" else row["PLT-01"]
                buckets[key] = bucket
            for field in SUM_FIELDS:
                bucket[field] = round(float(bucket[field]) + float(row.get(field) or 0), 2)

        result: list[dict[str, Any]] = []
        for (period, name), bucket in buckets.items():
            result.append(
                _row(
                    period=period,
                    platform=bucket["PLT-01"],
                    shop_name="合计" if level == "total" else f"{name} 小计",
                    shop_id="",
                    order_count=int(bucket["PLT-04"]),
                    shipped_count=int(bucket["PLT-05"]),
                    cancelled_count=int(bucket["PLT-06"]),
                    intake=float(bucket["PLT-08"]),
                    shipment=float(bucket["PLT-09"]),
                    cancelled=float(bucket["PLT-10"]),
                    # bucket 的 PLT-11 已含取消，这里只取「发货后售后」部分再交给 _row 组装
                    refund=round(float(bucket["PLT-11"]) - float(bucket["PLT-10"]), 2),
                    level=level,
                    row_id=f"{level}-{period}-{name}",
                )
            )
        result.sort(key=lambda item: (item["PLT-00"], item["PLT-12"]), reverse=True)
        return result

    async def page(
        self, search: PlatformAnalysisQueryParam, page_no: int, page_size: int
    ) -> dict[str, Any]:
        rows = await self._detail_rows(search.period_value)
        if search.platform:
            target = search.platform.strip()
            rows = [row for row in rows if row["PLT-01"] == target]
        if search.shop_id is not None:
            rows = [row for row in rows if row["PLT-03"] == search.shop_id]
        if search.keyword and search.keyword.strip():
            token = search.keyword.strip()
            rows = [
                row
                for row in rows
                if token in str(row["PLT-01"]) or token in str(row["PLT-02"]) or token == str(row["PLT-03"])
            ]

        platform_rows = self._aggregate(rows, "platform") if rows else []
        total_rows = self._aggregate(rows, "total") if rows else []
        if search.aggregate_level == "detail":
            combined = list(rows)
        elif search.aggregate_level == "platform":
            combined = platform_rows
        else:
            combined = total_rows + platform_rows + rows

        summary = self._summary(rows, platform_rows)
        total = len(combined)
        start = (page_no - 1) * page_size
        return {
            "items": combined[start : start + page_size],
            "columns": PLATFORM_FIELDS,
            "total": total,
            "page_no": page_no,
            "page_size": page_size,
            "has_next": start + page_size < total,
            "period_value": search.period_value,
            "tax_rate": retail_tax_rate(),
            "summary": summary,
        }

    def _summary(self, detail_rows: list[dict[str, Any]], platform_rows: list[dict[str, Any]]) -> dict[str, Any]:
        def _sum(field: str) -> float:
            return round(sum(float(row.get(field) or 0) for row in detail_rows), 2)

        intake = _sum("PLT-08")
        shipment = _sum("PLT-09")
        valid_orders = int(_sum("PLT-04")) - int(_sum("PLT-06"))
        # PLT-11 已含取消单（PLT-10），这里只按 PLT-11 取退货合计，避免重复
        return_abs = abs(_sum("PLT-11"))
        net = round(shipment - return_abs, 2)
        return {
            "period_value": detail_rows[0]["PLT-00"] if detail_rows else None,
            "shop_count": len(detail_rows),
            "platform_count": len(platform_rows),
            "order_count": int(_sum("PLT-04")),
            "shipped_order_count": int(_sum("PLT-05")),
            "cancelled_order_count": int(_sum("PLT-06")),
            "intake_untaxed_sum": intake,
            "shipment_untaxed_sum": shipment,
            "return_untaxed_sum": round(-return_abs, 2),
            "net_shipment_sum": net,
            "settlement_income_sum": round(net * settlement_rate() / 100, 2),
            "hq_allocation_sum": _sum("PLT-23"),
            "avg_order_value": round(intake / valid_orders, 2) if valid_orders > 0 else 0.0,
            "return_rate": _rate(return_abs, net, shipment),
            "top_platforms": sorted(
                [
                    {
                        "platform": row["PLT-01"],
                        "order_count": row["PLT-04"],
                        "intake_untaxed": row["PLT-08"],
                        "shipment_untaxed": row["PLT-09"],
                        "net_shipment": row["PLT-12"],
                        "settlement_income": row["PLT-13"],
                        "hq_allocation": row["PLT-23"],
                        "return_rate": row["PLT-37"],
                    }
                    for row in platform_rows
                ],
                key=lambda item: item["net_shipment"],
                reverse=True,
            )[:10],
        }

    async def stats(self, period_value: str | None) -> dict[str, Any]:
        rows = await self._detail_rows(period_value)
        return self._summary(rows, self._aggregate(rows, "platform") if rows else [])
