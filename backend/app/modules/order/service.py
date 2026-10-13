"""订单全链路查询与构建服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .build import build_period
from .fields import CORE_COLUMNS, FIELD_BY_CODE, FIELD_DEFS
from .model import OrderBuildRunModel, OrderFullChainModel

ROW_CORE_FIELDS = (
    "id",
    "order_number",
    "period_value",
    "calc_version",
    "trade_type",
    "order_type",
    "customer_id",
    "salesman_code",
    "order_date",
    "push_date",
    "finish_date",
    "ship_date",
    "qty",
    "intake_untaxed",
    "ship_untaxed",
    "net_shipment",
    "data_quality_flag",
)


def field_catalog() -> list[dict[str, Any]]:
    """字段目录（前端列定义与对外字段目录共用）。"""
    return [
        {
            "field_code": code,
            "field_name": name,
            "data_type": data_type,
            "group": group,
            "sensitive": sensitive,
            "excel_code": excel_code,
            "stored_in": "core" if code in CORE_COLUMNS else "extra",
        }
        for code, name, data_type, group, sensitive, excel_code in FIELD_DEFS
    ]


def flatten(row: OrderFullChainModel, sensitive: bool = True) -> dict[str, Any]:
    """宽表记录 → 扁平字段字典（核心列 + extra），供页面与对外接口使用。"""
    data: dict[str, Any] = {}
    for key in ROW_CORE_FIELDS:
        value = getattr(row, key, None)
        data[key] = value
    extra = row.extra or {}
    for key, value in extra.items():
        data[key] = value
    if not sensitive:
        for code, _name, _type, _group, is_sensitive, _excel in FIELD_DEFS:
            if is_sensitive:
                data.pop(code, None)
        data.pop("total_cost", None)
    return data


class OrderService:
    """订单全链路服务。"""

    def __init__(self, auth: AuthSchema | None, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def periods(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(OrderFullChainModel.period_value)
                .distinct()
                .order_by(OrderFullChainModel.period_value.desc())
            )
        ).scalars().all()
        return list(rows)

    async def latest_version(self, period_value: str) -> int:
        value = (
            await self.db.execute(
                select(func.max(OrderFullChainModel.calc_version)).where(
                    OrderFullChainModel.period_value == period_value
                )
            )
        ).scalar()
        return int(value or 0)

    async def resolve_scope(self, period_value: str | None, calc_version: int | None) -> tuple[str | None, int]:
        if not period_value:
            periods = await self.periods()
            period_value = periods[0] if periods else None
        if not period_value:
            return None, 0
        if not calc_version:
            calc_version = await self.latest_version(period_value)
        return period_value, calc_version

    async def page(self, search: Any, page_no: int = 1, page_size: int = 20) -> dict[str, Any]:
        period_value, calc_version = await self.resolve_scope(search.period_value, search.calc_version)
        empty = {
            "items": [],
            "columns": field_catalog(),
            "total": 0,
            "page_no": page_no,
            "page_size": page_size,
            "has_next": False,
            "period_value": period_value,
            "calc_version": calc_version,
            "summary": {},
        }
        if not period_value or not calc_version:
            return empty

        conditions = [
            OrderFullChainModel.period_value == period_value,
            OrderFullChainModel.calc_version == calc_version,
            OrderFullChainModel.is_deleted == False,  # noqa: E712
        ]
        if search.trade_type:
            conditions.append(OrderFullChainModel.trade_type == search.trade_type)
        if search.order_type:
            conditions.append(OrderFullChainModel.order_type == search.order_type)
        if search.order_number:
            conditions.append(OrderFullChainModel.order_number.like(f"%{search.order_number.strip()}%"))
        if search.salesman_code:
            conditions.append(OrderFullChainModel.salesman_code == search.salesman_code)
        if search.data_quality_flag:
            conditions.append(OrderFullChainModel.data_quality_flag.like(f"%{search.data_quality_flag.strip()}%"))
        if search.keyword:
            keyword = f"%{search.keyword.strip()}%"
            conditions.append(
                or_(
                    OrderFullChainModel.order_number.like(keyword),
                    OrderFullChainModel.extra["customer_name"].as_string().like(keyword),
                )
            )
        if search.customer_name:
            conditions.append(
                OrderFullChainModel.extra["customer_name"].as_string().like(f"%{search.customer_name.strip()}%")
            )

        total = (
            await self.db.execute(select(func.count()).select_from(OrderFullChainModel).where(*conditions))
        ).scalar() or 0
        rows = (
            await self.db.execute(
                select(OrderFullChainModel)
                .where(*conditions)
                .order_by(OrderFullChainModel.order_number)
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        summary = await self.summary(period_value, calc_version)
        return {
            "items": [flatten(row) for row in rows],
            "columns": field_catalog(),
            "total": int(total),
            "page_no": page_no,
            "page_size": page_size,
            "has_next": page_no * page_size < int(total),
            "period_value": period_value,
            "calc_version": calc_version,
            "summary": summary,
        }

    async def summary(self, period_value: str, calc_version: int) -> dict[str, Any]:
        base = [
            OrderFullChainModel.period_value == period_value,
            OrderFullChainModel.calc_version == calc_version,
            OrderFullChainModel.is_deleted == False,  # noqa: E712
        ]
        total = (await self.db.execute(select(func.count()).select_from(OrderFullChainModel).where(*base))).scalar() or 0
        cost_missing = (
            await self.db.execute(
                select(func.count())
                .select_from(OrderFullChainModel)
                .where(*base, OrderFullChainModel.data_quality_flag.like("%cost_missing%"))
            )
        ).scalar() or 0
        mo_unlinked = (
            await self.db.execute(
                select(func.count())
                .select_from(OrderFullChainModel)
                .where(*base, OrderFullChainModel.data_quality_flag.like("%mo_unlinked%"))
            )
        ).scalar() or 0
        intake = (
            await self.db.execute(select(func.sum(OrderFullChainModel.intake_untaxed)).where(*base))
        ).scalar()
        return {
            "order_count": int(total),
            "cost_missing_count": int(cost_missing),
            "mo_unlinked_count": int(mo_unlinked),
            "intake_untaxed_sum": float(intake or 0),
        }

    async def detail(self, order_number: str) -> dict[str, Any]:
        row = (
            await self.db.execute(
                select(OrderFullChainModel)
                .where(
                    OrderFullChainModel.order_number == order_number,
                    OrderFullChainModel.is_deleted == False,  # noqa: E712
                )
                .order_by(OrderFullChainModel.calc_version.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is None:
            # 业务性错误：明确 404，避免外部系统把「订单不存在」当成服务端故障
            raise CustomException(msg=f"订单 {order_number} 不存在", status_code=404)
        return {"item": flatten(row), "columns": field_catalog()}

    async def rebuild(self, period_value: str | None) -> dict[str, Any]:
        period_value, _ = await self.resolve_scope(period_value, None)
        if not period_value:
            raise CustomException(msg="没有可构建的期间，请先同步来源批次")
        return await build_period(self.db, period_value)

    async def runs(self, period_value: str | None = None, limit: int = 20) -> list[OrderBuildRunModel]:
        stmt = select(OrderBuildRunModel).where(OrderBuildRunModel.is_deleted == False)  # noqa: E712
        if period_value:
            stmt = stmt.where(OrderBuildRunModel.period_value == period_value)
        return list(
            (await self.db.execute(stmt.order_by(OrderBuildRunModel.id.desc()).limit(limit))).scalars().all()
        )


def field_by_code(code: str) -> tuple[str, str, str, str, bool] | None:
    return FIELD_BY_CODE.get(code)
