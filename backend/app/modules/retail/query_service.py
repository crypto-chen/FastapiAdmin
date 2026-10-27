"""零售订单/推送批次管理端查询。"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.setting import settings

from .model import (
    RetailAfterSaleItemModel,
    RetailAfterSaleModel,
    RetailOrderItemModel,
    RetailOrderModel,
    RetailSyncBatchModel,
)
from .schema import RetailAfterSaleQueryParam, RetailBatchQueryParam, RetailOrderQueryParam


def _dt(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _num(value: Any) -> float | None:
    return round(float(value), 4) if value is not None else None


def retail_tax_rate() -> float:
    """零售税率（百分比），默认 13；配置异常时回退 13。"""
    try:
        rate = float(settings.RETAIL_TAX_RATE)
    except (TypeError, ValueError):
        return 13.0
    return rate if rate >= 0 else 13.0


def untaxed(value: Any, rate: float | None = None) -> float | None:
    """含税金额折算未税：金额 / (1 + 税率/100)，保留 2 位小数。"""
    if value is None:
        return None
    rate = retail_tax_rate() if rate is None else rate
    amount = Decimal(str(value))
    if rate <= 0:
        return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    divisor = Decimal("1") + Decimal(str(rate)) / Decimal("100")
    return float((amount / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def shipped_statuses() -> list[str]:
    """「货物出货」判定用的订单状态；默认 Sent（已发货）。"""
    raw = getattr(settings, "RETAIL_SHIPPED_STATUSES", "Sent") or "Sent"
    items = [part.strip() for part in str(raw).split(",") if part.strip()]
    return items or ["Sent"]


def cancelled_statuses() -> list[str]:
    """计为退货退款的取消状态；默认 Cancelled（聚水潭「取消」）。"""
    raw = getattr(settings, "RETAIL_CANCELLED_STATUSES", "Cancelled") or "Cancelled"
    items = [part.strip() for part in str(raw).split(",") if part.strip()]
    return items or ["Cancelled"]


def settlement_rate() -> float:
    """营销结算收入比例（百分比），默认 10%。"""
    try:
        rate = float(getattr(settings, "RETAIL_SETTLEMENT_RATE", 10.0))
    except (TypeError, ValueError):
        return 10.0
    return rate if rate >= 0 else 10.0


def _order_row(row: RetailOrderModel) -> dict[str, Any]:
    is_shipped = (row.status or "") in shipped_statuses()
    return {
        "id": row.id,
        "source": row.source,
        "period_value": row.period_value,
        "shop_id": row.shop_id,
        "shop_name": row.shop_name,
        "so_id": row.so_id,
        "o_id": row.o_id,
        "co_id": row.co_id,
        "status": row.status,
        "order_from": row.order_from,
        "buyer_nick": row.buyer_nick,
        "order_date": _dt(row.order_date),
        "pay_date": _dt(row.pay_date),
        "modified_time": _dt(row.modified_time),
        "paid_amount": _num(row.paid_amount),
        "pay_amount": _num(row.pay_amount),
        "buyer_paid_amount": _num(row.buyer_paid_amount),
        "seller_income_amount": _num(row.seller_income_amount),
        "untaxed_amount": untaxed(row.buyer_paid_amount),
        "is_shipped": is_shipped,
        # 货物出货（PLT-09）：只统计已发货订单，未发货记 0
        "shipped_untaxed_amount": (untaxed(row.buyer_paid_amount) or 0.0) if is_shipped else 0.0,
        "freight": _num(row.freight),
        "free_amount": _num(row.free_amount),
        "receiver_state": row.receiver_state,
        "receiver_city": row.receiver_city,
        "receiver_district": row.receiver_district,
        "receiver_town": row.receiver_town,
        "remark": row.remark,
        "item_count": row.item_count,
        "last_batch_id": row.last_batch_id,
        "created_time": _dt(row.created_time),
        "updated_time": _dt(row.updated_time),
    }


def _item_row(row: RetailOrderItemModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "oi_id": row.oi_id,
        "sku_id": row.sku_id,
        "i_id": row.i_id,
        "name": row.name,
        "properties_value": row.properties_value,
        "qty": _num(row.qty),
        "price": _num(row.price),
        "base_price": _num(row.base_price),
        "amount": _num(row.amount),
        "buyer_paid_amount": _num(row.buyer_paid_amount),
        "seller_income_amount": _num(row.seller_income_amount),
        "item_pay_amount": _num(row.item_pay_amount),
        "item_status": row.item_status,
        "refund_status": row.refund_status,
        "is_gift": bool(row.is_gift),
        "src_combine_sku_id": row.src_combine_sku_id,
    }


def _batch_row(row: RetailSyncBatchModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "app_id": row.app_id,
        "biz_type": (row.params or {}).get("biz_type") or "order",
        "request_id": row.request_id,
        "source": row.source,
        "status": row.status,
        "received_count": row.received_count,
        "created_count": row.created_count,
        "updated_count": row.updated_count,
        "unchanged_count": row.unchanged_count,
        "stale_count": row.stale_count,
        "failed_count": row.failed_count,
        "item_count": row.item_count,
        "periods": list(row.periods or []),
        "has_next": bool(row.has_next),
        "page_index": row.page_index,
        "page_size": row.page_size,
        "created_time": _dt(row.created_time),
    }


def _aftersale_row(row: RetailAfterSaleModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "period_value": row.period_value,
        "as_id": row.as_id,
        "outer_as_id": row.outer_as_id,
        "o_id": row.o_id,
        "so_id": row.so_id,
        "shop_id": row.shop_id,
        "shop_name": row.shop_name,
        "shop_site": row.shop_site,
        "type": row.type,
        "status": row.status,
        "shop_status": row.shop_status,
        "good_status": row.good_status,
        "order_status": row.order_status,
        "as_date": _dt(row.as_date),
        "registered_time": _dt(row.registered_time),
        "modified_time": _dt(row.modified_time),
        "confirm_date": _dt(row.confirm_date),
        "refund": _num(row.refund),
        "freight": _num(row.freight),
        "payment": _num(row.payment),
        "free_amount": _num(row.free_amount),
        "actual_refund": _num(row.actual_refund),
        "untaxed_actual_refund": untaxed(row.actual_refund),
        "buyer_apply_refund": _num(row.buyer_apply_refund),
        "receive_refund": _num(row.receive_refund),
        "seller_real_refund": _num(row.seller_real_refund),
        "buyer_paid_amount": _num(row.buyer_paid_amount),
        "seller_income_amount": _num(row.seller_income_amount),
        "l_id": row.l_id,
        "logistics_company": row.logistics_company,
        "warehouse": row.warehouse,
        "remark": row.remark,
        "item_count": row.item_count,
        "last_batch_id": row.last_batch_id,
        "created_time": _dt(row.created_time),
        "updated_time": _dt(row.updated_time),
    }


def _aftersale_item_row(row: RetailAfterSaleItemModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "asi_id": row.asi_id,
        "sku_id": row.sku_id,
        "i_id": row.i_id,
        "name": row.name,
        "properties_value": row.properties_value,
        "qty": _num(row.qty),
        "r_qty": _num(row.r_qty),
        "defective_qty": _num(row.defective_qty),
        "price": _num(row.price),
        "amount": _num(row.amount),
        "shop_amount": _num(row.shop_amount),
        "buyer_paid_amount": _num(row.buyer_paid_amount),
        "seller_income_amount": _num(row.seller_income_amount),
        "type": row.type,
        "is_gift": bool(row.is_gift),
        "outer_oi_id": row.outer_oi_id,
    }


class RetailQueryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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

    @staticmethod
    def _order_conditions(search: RetailOrderQueryParam) -> list:
        conditions = [RetailOrderModel.is_deleted == False]  # noqa: E712
        if search.period_value:
            conditions.append(RetailOrderModel.period_value == search.period_value.strip())
        if search.shop_id is not None:
            conditions.append(RetailOrderModel.shop_id == search.shop_id)
        if search.shop_name and search.shop_name.strip():
            conditions.append(RetailOrderModel.shop_name.like(f"%{search.shop_name.strip()}%"))
        if search.so_id and search.so_id.strip():
            token = f"%{search.so_id.strip()}%"
            conditions.append(or_(RetailOrderModel.so_id.like(token), RetailOrderModel.o_id.like(token)))
        if search.status and search.status.strip():
            conditions.append(RetailOrderModel.status == search.status.strip())
        if search.source and search.source.strip():
            conditions.append(RetailOrderModel.source == search.source.strip())
        if search.keyword and search.keyword.strip():
            token = f"%{search.keyword.strip()}%"
            conditions.append(
                or_(
                    RetailOrderModel.so_id.like(token),
                    RetailOrderModel.o_id.like(token),
                    RetailOrderModel.shop_name.like(token),
                    RetailOrderModel.buyer_nick.like(token),
                    RetailOrderModel.remark.like(token),
                )
            )
        return conditions

    async def page_orders(
        self, search: RetailOrderQueryParam, page_no: int, page_size: int
    ) -> dict[str, Any]:
        conditions = self._order_conditions(search)
        total = (
            await self.db.execute(select(func.count(RetailOrderModel.id)).where(*conditions))
        ).scalar() or 0
        amounts = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(RetailOrderModel.buyer_paid_amount), 0),
                    func.coalesce(func.sum(RetailOrderModel.item_count), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    RetailOrderModel.status.in_(shipped_statuses()),
                                    RetailOrderModel.buyer_paid_amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (RetailOrderModel.status.in_(shipped_statuses()), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(*conditions)
            )
        ).first()
        rows = (
            await self.db.execute(
                select(RetailOrderModel)
                .where(*conditions)
                .order_by(RetailOrderModel.modified_time.desc(), RetailOrderModel.id.desc())
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        tax_rate = retail_tax_rate()
        paid_sum = _num(amounts[0]) if amounts else 0
        shipped_sum = _num(amounts[2]) if amounts else 0
        return {
            "items": [_order_row(row) for row in rows],
            "total": int(total),
            "page_no": page_no,
            "page_size": page_size,
            "has_next": page_no * page_size < int(total),
            "summary": {
                "order_count": int(total),
                "buyer_paid_amount_sum": paid_sum,
                "untaxed_amount_sum": untaxed(paid_sum, tax_rate),
                "shipped_order_count": int(amounts[3]) if amounts else 0,
                "shipped_amount_sum": shipped_sum,
                "shipped_untaxed_amount_sum": untaxed(shipped_sum, tax_rate),
                "tax_rate": tax_rate,
                "item_count_sum": int(amounts[1]) if amounts else 0,
            },
        }

    async def order_detail(self, order_id: int) -> dict[str, Any]:
        order = await self.db.get(RetailOrderModel, order_id)
        if order is None or order.is_deleted:
            return {}
        items = (
            await self.db.execute(
                select(RetailOrderItemModel)
                .where(RetailOrderItemModel.order_id == order.id)
                .order_by(RetailOrderItemModel.id.asc())
            )
        ).scalars().all()
        return {"order": _order_row(order), "items": [_item_row(item) for item in items]}

    async def page_batches(
        self, search: RetailBatchQueryParam, page_no: int, page_size: int
    ) -> dict[str, Any]:
        conditions = [RetailSyncBatchModel.is_deleted == False]  # noqa: E712
        if search.biz_type and search.biz_type.strip():
            # 订单批次 params 为空，售后批次 params.biz_type=after_sale
            if search.biz_type.strip() == "order":
                conditions.append(
                    or_(
                        RetailSyncBatchModel.params.is_(None),
                        RetailSyncBatchModel.params["biz_type"].as_string().is_(None),
                    )
                )
            else:
                conditions.append(
                    RetailSyncBatchModel.params["biz_type"].as_string() == search.biz_type.strip()
                )
        if search.request_id and search.request_id.strip():
            conditions.append(RetailSyncBatchModel.request_id.like(f"%{search.request_id.strip()}%"))
        if search.app_id and search.app_id.strip():
            conditions.append(RetailSyncBatchModel.app_id == search.app_id.strip())
        if search.source and search.source.strip():
            conditions.append(RetailSyncBatchModel.source == search.source.strip())
        if search.status and search.status.strip():
            conditions.append(RetailSyncBatchModel.status == search.status.strip())
        total = (
            await self.db.execute(select(func.count(RetailSyncBatchModel.id)).where(*conditions))
        ).scalar() or 0
        rows = (
            await self.db.execute(
                select(RetailSyncBatchModel)
                .where(*conditions)
                .order_by(RetailSyncBatchModel.created_time.desc(), RetailSyncBatchModel.id.desc())
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "items": [_batch_row(row) for row in rows],
            "total": int(total),
            "page_no": page_no,
            "page_size": page_size,
            "has_next": page_no * page_size < int(total),
        }

    async def batch_detail(self, batch_id: int) -> dict[str, Any]:
        row = await self.db.get(RetailSyncBatchModel, batch_id)
        if row is None or row.is_deleted:
            return {}
        data = _batch_row(row)
        data.update(
            {
                "params": row.params or {},
                "errors": row.errors or [],
                "result": row.result or {},
            }
        )
        return data

    @staticmethod
    def _aftersale_conditions(search: RetailAfterSaleQueryParam) -> list:
        conditions = [RetailAfterSaleModel.is_deleted == False]  # noqa: E712
        if search.period_value:
            conditions.append(RetailAfterSaleModel.period_value == search.period_value.strip())
        if search.shop_id is not None:
            conditions.append(RetailAfterSaleModel.shop_id == search.shop_id)
        if search.shop_name and search.shop_name.strip():
            conditions.append(RetailAfterSaleModel.shop_name.like(f"%{search.shop_name.strip()}%"))
        if search.as_id and search.as_id.strip():
            token = f"%{search.as_id.strip()}%"
            conditions.append(
                or_(RetailAfterSaleModel.as_id.like(token), RetailAfterSaleModel.outer_as_id.like(token))
            )
        if search.so_id and search.so_id.strip():
            token = f"%{search.so_id.strip()}%"
            conditions.append(
                or_(RetailAfterSaleModel.so_id.like(token), RetailAfterSaleModel.o_id.like(token))
            )
        if search.status and search.status.strip():
            conditions.append(RetailAfterSaleModel.status == search.status.strip())
        if search.type and search.type.strip():
            conditions.append(RetailAfterSaleModel.type == search.type.strip())
        if search.keyword and search.keyword.strip():
            token = f"%{search.keyword.strip()}%"
            conditions.append(
                or_(
                    RetailAfterSaleModel.as_id.like(token),
                    RetailAfterSaleModel.outer_as_id.like(token),
                    RetailAfterSaleModel.so_id.like(token),
                    RetailAfterSaleModel.o_id.like(token),
                    RetailAfterSaleModel.shop_name.like(token),
                    RetailAfterSaleModel.remark.like(token),
                )
            )
        return conditions

    async def page_aftersales(
        self, search: RetailAfterSaleQueryParam, page_no: int, page_size: int
    ) -> dict[str, Any]:
        conditions = self._aftersale_conditions(search)
        total = (
            await self.db.execute(select(func.count(RetailAfterSaleModel.id)).where(*conditions))
        ).scalar() or 0
        sums = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(RetailAfterSaleModel.actual_refund), 0),
                    func.coalesce(func.sum(RetailAfterSaleModel.refund), 0),
                    func.coalesce(func.sum(RetailAfterSaleModel.item_count), 0),
                ).where(*conditions)
            )
        ).first()
        rows = (
            await self.db.execute(
                select(RetailAfterSaleModel)
                .where(*conditions)
                .order_by(RetailAfterSaleModel.as_date.desc(), RetailAfterSaleModel.id.desc())
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        tax_rate = retail_tax_rate()
        actual_sum = _num(sums[0]) if sums else 0
        return {
            "items": [_aftersale_row(row) for row in rows],
            "total": int(total),
            "page_no": page_no,
            "page_size": page_size,
            "has_next": page_no * page_size < int(total),
            "summary": {
                "after_sale_count": int(total),
                "actual_refund_sum": actual_sum,
                "untaxed_actual_refund_sum": untaxed(actual_sum, tax_rate),
                "tax_rate": tax_rate,
                "refund_sum": _num(sums[1]) if sums else 0,
                "item_count_sum": int(sums[2]) if sums else 0,
            },
        }

    async def aftersale_detail(self, after_sale_id: int) -> dict[str, Any]:
        row = await self.db.get(RetailAfterSaleModel, after_sale_id)
        if row is None or row.is_deleted:
            return {}
        items = (
            await self.db.execute(
                select(RetailAfterSaleItemModel)
                .where(RetailAfterSaleItemModel.after_sale_id == row.id)
                .order_by(RetailAfterSaleItemModel.id.asc())
            )
        ).scalars().all()
        data = _aftersale_row(row)
        data.update(
            {
                "platform_promotion": _num(row.platform_promotion),
                "platform_free_amount": _num(row.platform_free_amount),
                "government_free_amount": _num(row.government_free_amount),
                "currency": row.currency,
                "result": row.result,
                "node": row.node,
                "wms_co_id": row.wms_co_id,
            }
        )
        return {"after_sale": data, "items": [_aftersale_item_row(item) for item in items]}

    async def analysis_summary(
        self,
        period_value: str | None = None,
        shop_id: int | None = None,
    ) -> dict[str, Any]:
        """按「期间 × 店铺」输出平台店铺分析口径（PLT-08/09/11/12/37）。

        - 接单未税 PLT-08：该期间订单买家实付 ÷ 1.13（含后续取消的单）；
        - 货物出货未税 PLT-09：**订单状态已发货**（默认 ``Sent``）的订单金额 ÷ 1.13；
        - 退货退款 PLT-11（负数，2026-10-27 确认口径）：
          「订单状态=取消」的订单金额 + 「发货后申请退款」的售后实退，均 ÷ 1.13；
        - 未发货订单上的售后（订单仍是 WaitConfirm/Delivering）不计入，避免与取消重复；
        - 对外出货净额 PLT-12 = PLT-09 + PLT-11；
        - 营销结算收入 PLT-13 = PLT-12 × 10%（``RETAIL_SETTLEMENT_RATE`` 可配）；
        - 退货率 PLT-37 = |PLT-11| ÷ PLT-12（PLT-12 ≤ 0 时改用 PLT-09 作分母）。
        """
        statuses = shipped_statuses()
        cancelled = cancelled_statuses()
        rate_pct = settlement_rate()
        tax_rate = retail_tax_rate()
        order_conditions = [
            RetailOrderModel.is_deleted == False,  # noqa: E712
            RetailOrderModel.status.notin_(["Delete"]),
        ]
        refund_conditions = [RetailAfterSaleModel.is_deleted == False]  # noqa: E712
        if period_value and period_value.strip():
            period = period_value.strip()
            order_conditions.append(RetailOrderModel.period_value == period)
            refund_conditions.append(RetailAfterSaleModel.period_value == period)
        if shop_id is not None:
            order_conditions.append(RetailOrderModel.shop_id == shop_id)
            refund_conditions.append(RetailAfterSaleModel.shop_id == shop_id)

        order_rows = (
            await self.db.execute(
                select(
                    RetailOrderModel.period_value,
                    RetailOrderModel.shop_id,
                    func.max(RetailOrderModel.shop_name),
                    func.count(RetailOrderModel.id),
                    func.coalesce(func.sum(RetailOrderModel.buyer_paid_amount), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    RetailOrderModel.status.in_(statuses),
                                    RetailOrderModel.buyer_paid_amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((RetailOrderModel.status.in_(statuses), 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    RetailOrderModel.status.in_(cancelled),
                                    RetailOrderModel.buyer_paid_amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((RetailOrderModel.status.in_(cancelled), 1), else_=0)), 0
                    ),
                )
                .where(*order_conditions)
                .group_by(RetailOrderModel.period_value, RetailOrderModel.shop_id)
                .order_by(RetailOrderModel.period_value.desc(), RetailOrderModel.shop_id.asc())
            )
        ).all()

        refund_rows = (
            await self.db.execute(
                select(
                    RetailAfterSaleModel.period_value,
                    RetailAfterSaleModel.shop_id,
                    func.coalesce(func.sum(RetailAfterSaleModel.actual_refund), 0),
                )
                .where(*refund_conditions)
                .group_by(RetailAfterSaleModel.period_value, RetailAfterSaleModel.shop_id)
            )
        ).all()
        refund_index = {
            (str(row[0]), int(row[1])): float(row[2] or 0) for row in refund_rows
        }

        # 「发货后申请退款」判定：售后单能匹配到订单，且订单状态已发货。
        # 匹配不到订单的售后单（如淘系订单未推送）仍计入，避免漏退款。
        order_state = (
            select(
                RetailOrderModel.shop_id.label("shop_id"),
                RetailOrderModel.so_id.label("so_id"),
                func.min(RetailOrderModel.status).label("status"),
            )
            .where(
                RetailOrderModel.is_deleted == False,  # noqa: E712
                RetailOrderModel.so_id.isnot(None),
            )
            .group_by(RetailOrderModel.shop_id, RetailOrderModel.so_id)
            .subquery()
        )
        not_shipped_rows = (
            await self.db.execute(
                select(
                    RetailAfterSaleModel.period_value,
                    RetailAfterSaleModel.shop_id,
                    func.coalesce(func.sum(RetailAfterSaleModel.actual_refund), 0),
                )
                .join(
                    order_state,
                    and_(
                        order_state.c.shop_id == RetailAfterSaleModel.shop_id,
                        order_state.c.so_id == RetailAfterSaleModel.so_id,
                    ),
                )
                .where(
                    *refund_conditions,
                    order_state.c.status.notin_(statuses),
                )
                .group_by(RetailAfterSaleModel.period_value, RetailAfterSaleModel.shop_id)
            )
        ).all()
        not_shipped_index = {
            (str(row[0]), int(row[1])): float(row[2] or 0) for row in not_shipped_rows
        }

        items: list[dict[str, Any]] = []
        total_intake = total_shipment = total_refund = total_cancelled = 0.0
        total_orders = total_shipped = total_cancelled_orders = 0
        seen_refund_keys: set[tuple[str, int]] = set()
        for row in order_rows:
            period, shop = str(row[0]), int(row[1])
            intake = untaxed(row[4], tax_rate) or 0.0
            shipment = untaxed(row[5], tax_rate) or 0.0
            gross_refund = refund_index.get((period, shop), 0.0)
            refund = untaxed(
                max(gross_refund - not_shipped_index.get((period, shop), 0.0), 0.0), tax_rate
            ) or 0.0
            cancelled_amount = untaxed(row[7], tax_rate) or 0.0
            seen_refund_keys.add((period, shop))
            return_total = round(cancelled_amount + refund, 2)
            net = round(shipment - return_total, 2)
            settlement = round(net * rate_pct / 100, 2)
            rate_base = net if net > 0 else shipment
            items.append(
                {
                    "period_value": period,
                    "shop_id": shop,
                    "shop_name": row[2],
                    "order_count": int(row[3]),
                    "shipped_order_count": int(row[6]),
                    "cancelled_order_count": int(row[8]),
                    "intake_untaxed": intake,
                    "shipment_untaxed": shipment,
                    "cancelled_untaxed": round(-cancelled_amount, 2),
                    "refund_untaxed": round(-refund, 2),
                    "return_untaxed": round(-return_total, 2),
                    "net_shipment_untaxed": net,
                    "settlement_income_untaxed": settlement,
                    "return_rate": round(return_total / rate_base, 4) if rate_base else 0.0,
                }
            )
            total_orders += int(row[3])
            total_shipped += int(row[6])
            total_cancelled_orders += int(row[8])
            total_intake += intake
            total_shipment += shipment
            total_refund += refund
            total_cancelled += cancelled_amount

        # 只有售后、没有当期订单的店铺也要露出来（否则退货被吞掉）
        for (period, shop), amount in refund_index.items():
            if (period, shop) in seen_refund_keys:
                continue
            refund = untaxed(
                max(amount - not_shipped_index.get((period, shop), 0.0), 0.0), tax_rate
            ) or 0.0
            items.append(
                {
                    "period_value": period,
                    "shop_id": shop,
                    "shop_name": None,
                    "order_count": 0,
                    "shipped_order_count": 0,
                    "cancelled_order_count": 0,
                    "intake_untaxed": 0.0,
                    "shipment_untaxed": 0.0,
                    "cancelled_untaxed": 0.0,
                    "refund_untaxed": round(-refund, 2),
                    "return_untaxed": round(-refund, 2),
                    "net_shipment_untaxed": round(-refund, 2),
                    "settlement_income_untaxed": round(-refund * rate_pct / 100, 2),
                    "return_rate": 0.0,
                }
            )
            total_refund += refund

        return_total = round(total_cancelled + total_refund, 2)
        net_total = round(total_shipment - return_total, 2)
        settlement_total = round(net_total * rate_pct / 100, 2)
        rate_base = net_total if net_total > 0 else total_shipment
        return {
            "tax_rate": tax_rate,
            "settlement_rate": rate_pct,
            "shipped_statuses": statuses,
            "cancelled_statuses": cancelled,
            "items": items,
            "total": {
                "shop_count": len({(item["period_value"], item["shop_id"]) for item in items}),
                "order_count": total_orders,
                "shipped_order_count": total_shipped,
                "cancelled_order_count": total_cancelled_orders,
                "intake_untaxed": round(total_intake, 2),
                "shipment_untaxed": round(total_shipment, 2),
                "cancelled_untaxed": round(-total_cancelled, 2),
                "refund_untaxed": round(-total_refund, 2),
                "return_untaxed": round(-return_total, 2),
                "net_shipment_untaxed": net_total,
                "settlement_income_untaxed": settlement_total,
                "return_rate": round(return_total / rate_base, 4) if rate_base else 0.0,
            },
        }
