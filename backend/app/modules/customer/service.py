"""客户分析查询与构建服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .build import build_period
from .fields import CORE_COLUMNS, FIELD_DEFS, FIELD_ORDER
from .model import CustomerAnalysisModel, CustomerBuildRunModel
from .schema import CustomerQueryParam

ROW_CORE_FIELDS = (
    "id",
    "period_value",
    "calc_version",
    "is_aggregate",
    "customer_id",
    "customer_code",
    "customer_name",
    "salesman_code",
    "salesman_name",
    "order_count",
    "intake_untaxed",
    "net_shipment",
    "gross_profit",
    "contribution_margin",
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
            "excel_code": code,
            "source": source,
            "note": note,
            "stored_in": "core" if code in CORE_COLUMNS else "extra",
        }
        for code, name, data_type, group, sensitive, source, note in FIELD_DEFS
    ]


def flatten(row: CustomerAnalysisModel, sensitive: bool = True) -> dict[str, Any]:
    """宽表记录 → 扁平字段字典（核心列 + extra，CUS-xx 置顶）。"""
    extra = row.extra or {}
    data: dict[str, Any] = {code: extra.get(code) for code in FIELD_ORDER}
    for key in ROW_CORE_FIELDS:
        data[key] = getattr(row, key, None)
    data["is_aggregate"] = bool(row.is_aggregate)
    for key, value in extra.items():
        data.setdefault(key, value)
    if not sensitive:
        for code, _name, _type, _group, is_sensitive, _source, _note in FIELD_DEFS:
            if is_sensitive:
                data.pop(code, None)
    return data


class CustomerService:
    """客户分析服务。"""

    def __init__(self, auth: AuthSchema | None, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def periods(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(CustomerAnalysisModel.period_value)
                .distinct()
                .order_by(CustomerAnalysisModel.period_value.desc())
            )
        ).scalars().all()
        return list(rows)

    async def latest_version(self, period_value: str) -> int:
        value = (
            await self.db.execute(
                select(func.max(CustomerAnalysisModel.calc_version)).where(
                    CustomerAnalysisModel.period_value == period_value
                )
            )
        ).scalar()
        return int(value or 0)

    async def latest_period(self) -> str | None:
        return (
            await self.db.execute(
                select(func.max(CustomerAnalysisModel.period_value))
            )
        ).scalar()

    async def page(
        self, search: CustomerQueryParam, page_no: int, page_size: int
    ) -> dict[str, Any]:
        period = search.period_value or await self.latest_period()
        if not period:
            return {
                "items": [],
                "columns": field_catalog(),
                "total": 0,
                "page_no": page_no,
                "page_size": page_size,
                "has_next": False,
                "period_value": None,
                "calc_version": 0,
                "summary": {},
            }
        version = search.calc_version or await self.latest_version(period)
        conditions = [
            CustomerAnalysisModel.period_value == period,
            CustomerAnalysisModel.calc_version == version,
        ]
        if not search.include_aggregate:
            conditions.append(CustomerAnalysisModel.is_aggregate == 0)
        if search.customer_code:
            conditions.append(CustomerAnalysisModel.customer_code.like(f"%{search.customer_code}%"))
        if search.customer_name:
            conditions.append(CustomerAnalysisModel.customer_name.like(f"%{search.customer_name}%"))
        if search.salesman_code:
            conditions.append(CustomerAnalysisModel.salesman_code == search.salesman_code)
        if search.keyword:
            conditions.append(
                or_(
                    CustomerAnalysisModel.customer_code.like(f"%{search.keyword}%"),
                    CustomerAnalysisModel.customer_name.like(f"%{search.keyword}%"),
                )
            )
        total = (
            await self.db.execute(select(func.count()).select_from(CustomerAnalysisModel).where(*conditions))
        ).scalar() or 0
        rows = (
            await self.db.execute(
                select(CustomerAnalysisModel)
                .where(*conditions)
                .order_by(CustomerAnalysisModel.is_aggregate.asc(), CustomerAnalysisModel.intake_untaxed.desc())
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        items = [flatten(row) for row in rows]
        # 多值字段（订单类型/产品线）在 Python 侧过滤（存的是拼接串）
        if search.order_type:
            items = [item for item in items if search.order_type in str(item.get("CUS-11") or "")]
        if search.product_line:
            items = [item for item in items if search.product_line in str(item.get("CUS-09") or "")]
        if search.trade_type:
            items = [item for item in items if search.trade_type in str(item.get("CUS-05") or "")]
        aggregate = next((item for item in items if item.get("is_aggregate")), None)
        return {
            "items": items,
            "columns": field_catalog(),
            "total": total,
            "page_no": page_no,
            "page_size": page_size,
            "has_next": page_no * page_size < total,
            "period_value": period,
            "calc_version": version,
            "summary": {
                "customer_count": (aggregate or {}).get("CUS-43"),
                "order_count": (aggregate or {}).get("order_count"),
                "intake_untaxed_sum": (aggregate or {}).get("CUS-12"),
                "net_shipment_sum": (aggregate or {}).get("CUS-16"),
            },
        }

    async def detail(self, customer_code: str) -> dict[str, Any]:
        period = await self.latest_period()
        version = await self.latest_version(period) if period else 0
        row = (
            await self.db.execute(
                select(CustomerAnalysisModel).where(
                    CustomerAnalysisModel.customer_code == customer_code,
                    CustomerAnalysisModel.period_value == period,
                    CustomerAnalysisModel.calc_version == version,
                )
            )
        ).scalars().first()
        if row is None:
            raise CustomException(msg=f"客户 {customer_code} 在期间 {period} 没有数据")
        return {"item": flatten(row), "columns": field_catalog(), "period_value": period}

    async def runs(self, period_value: str | None, limit: int) -> list[CustomerBuildRunModel]:
        statement = select(CustomerBuildRunModel).order_by(CustomerBuildRunModel.id.desc()).limit(limit)
        if period_value:
            statement = statement.where(CustomerBuildRunModel.period_value == period_value)
        return list((await self.db.execute(statement)).scalars().all())

    async def rebuild(self, period_value: str | None) -> dict[str, Any]:
        period = period_value or await self.latest_period() or None
        if not period:
            from datetime import datetime

            period = datetime.now().strftime("%Y-%m")
        try:
            return await build_period(self.db, period)
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            raise CustomException(msg=f"客户分析构建失败：{exc}") from exc
