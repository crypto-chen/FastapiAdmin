"""产品线分析查询与构建服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .build import build_period
from .fields import CORE_COLUMNS, FIELD_DEFS, FIELD_ORDER, STATUS_LABELS
from .model import ProductLineAnalysisModel, ProductLineBuildRunModel
from .schema import ProductLineQueryParam

ROW_CORE_FIELDS = (
    "id",
    "period_value",
    "calc_version",
    "is_aggregate",
    "product_line_code",
    "product_line_name",
    "sku",
    "order_count",
    "ship_qty",
    "intake_untaxed",
    "ship_untaxed",
    "net_shipment",
    "gross_profit",
    "contribution_margin",
    "data_quality_flag",
)


def field_catalog() -> list[dict[str, Any]]:
    """字段目录（前端列定义与字段说明抽屉共用）。"""
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
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "stored_in": "core" if code in CORE_COLUMNS else "extra",
        }
        for code, name, data_type, group, sensitive, source, status, note in FIELD_DEFS
    ]


def flatten(row: ProductLineAnalysisModel, sensitive: bool = True) -> dict[str, Any]:
    """宽表记录 → 扁平字段字典（核心列 + extra，PRD-xx 置顶）。"""
    extra = row.extra or {}
    data: dict[str, Any] = {code: extra.get(code) for code in FIELD_ORDER}
    for key in ROW_CORE_FIELDS:
        data[key] = getattr(row, key, None)
    data["is_aggregate"] = int(row.is_aggregate or 0)
    data["PRD-00"] = row.period_value
    for key, value in extra.items():
        data.setdefault(key, value)
    if not sensitive:
        for code, _name, _type, _group, is_sensitive, _source, _status, _note in FIELD_DEFS:
            if is_sensitive:
                data.pop(code, None)
    return data


class ProductLineService:
    """产品线分析服务。"""

    def __init__(self, auth: AuthSchema | None, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def periods(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(ProductLineAnalysisModel.period_value)
                .distinct()
                .order_by(ProductLineAnalysisModel.period_value.desc())
            )
        ).scalars().all()
        return list(rows)

    async def latest_version(self, period_value: str) -> int:
        value = (
            await self.db.execute(
                select(func.max(ProductLineAnalysisModel.calc_version)).where(
                    ProductLineAnalysisModel.period_value == period_value
                )
            )
        ).scalar()
        return int(value or 0)

    async def latest_period(self) -> str | None:
        return (
            await self.db.execute(select(func.max(ProductLineAnalysisModel.period_value)))
        ).scalar()

    async def product_lines(self, period_value: str | None = None) -> list[str]:
        """产品线大类候选（前端下拉，来自已构建结果）。"""
        period = period_value or await self.latest_period()
        if not period:
            return []
        version = await self.latest_version(period)
        rows = (
            await self.db.execute(
                select(ProductLineAnalysisModel.product_line_code)
                .where(
                    ProductLineAnalysisModel.period_value == period,
                    ProductLineAnalysisModel.calc_version == version,
                    ProductLineAnalysisModel.is_aggregate.in_((0, 1)),
                )
                .distinct()
                .order_by(ProductLineAnalysisModel.product_line_code)
            )
        ).scalars().all()
        return [item for item in rows if item]

    async def stats(self, period_value: str | None = None) -> dict[str, Any]:
        """期间汇总（顶部指标卡）：取合计行 + 产品线小计行 TopN。"""
        period = period_value or await self.latest_period()
        if not period:
            return {}
        version = await self.latest_version(period)
        base = (
            ProductLineAnalysisModel.period_value == period,
            ProductLineAnalysisModel.calc_version == version,
        )
        total = (
            await self.db.execute(
                select(ProductLineAnalysisModel).where(*base, ProductLineAnalysisModel.is_aggregate == 2)
            )
        ).scalars().first()
        lines = (
            await self.db.execute(
                select(ProductLineAnalysisModel)
                .where(*base, ProductLineAnalysisModel.is_aggregate == 1)
                .order_by(ProductLineAnalysisModel.net_shipment.desc())
            )
        ).scalars().all()
        sku_count = (
            await self.db.execute(
                select(func.count(func.distinct(ProductLineAnalysisModel.sku))).where(
                    *base, ProductLineAnalysisModel.is_aggregate == 0
                )
            )
        ).scalar() or 0
        line_items: list[dict[str, Any]] = []
        for row in lines:
            extra = row.extra or {}
            line_items.append(
                {
                    "product_line": row.product_line_code,
                    "order_count": row.order_count,
                    "intake_untaxed": float(row.intake_untaxed or 0),
                    "ship_untaxed": float(row.ship_untaxed or 0),
                    "net_shipment": float(row.net_shipment or 0),
                    "settlement_income": float(extra.get("PRD-27") or 0),
                    "hq_allocation": float(extra.get("PRD-33") or 0),
                }
            )
        total_extra = (total.extra or {}) if total else {}
        return {
            "period_value": period,
            "calc_version": version,
            "line_count": len(line_items),
            "sku_count": int(sku_count),
            "order_count": int(total.order_count) if total else 0,
            "intake_untaxed_sum": float(total.intake_untaxed or 0) if total else 0.0,
            "ship_untaxed_sum": float(total.ship_untaxed or 0) if total else 0.0,
            "net_shipment_sum": float(total.net_shipment or 0) if total else 0.0,
            "settlement_income_sum": float(total_extra.get("PRD-27") or 0),
            "hq_allocation_sum": float(total_extra.get("PRD-33") or 0),
            "top_lines": line_items[:10],
        }

    async def page(self, search: ProductLineQueryParam, page_no: int, page_size: int) -> dict[str, Any]:
        period = search.period_value or await self.latest_period()
        empty = {
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
        if not period:
            return empty
        version = search.calc_version or await self.latest_version(period)
        conditions: list[Any] = [
            ProductLineAnalysisModel.period_value == period,
            ProductLineAnalysisModel.calc_version == version,
        ]
        level = (search.aggregate_level or "detail").lower()
        if level == "detail":
            conditions.append(ProductLineAnalysisModel.is_aggregate == 0)
        elif level == "line":
            conditions.append(ProductLineAnalysisModel.is_aggregate.in_((1, 2)))
        if search.product_line:
            conditions.append(ProductLineAnalysisModel.product_line_code.like(f"%{search.product_line}%"))
        if search.sku:
            conditions.append(ProductLineAnalysisModel.sku.like(f"%{search.sku}%"))
        if search.keyword:
            conditions.append(
                or_(
                    ProductLineAnalysisModel.product_line_code.like(f"%{search.keyword}%"),
                    ProductLineAnalysisModel.sku.like(f"%{search.keyword}%"),
                )
            )
        total = (
            await self.db.execute(
                select(func.count()).select_from(ProductLineAnalysisModel).where(*conditions)
            )
        ).scalar() or 0
        rows = (
            await self.db.execute(
                select(ProductLineAnalysisModel)
                .where(*conditions)
                .order_by(
                    ProductLineAnalysisModel.is_aggregate.asc(),
                    ProductLineAnalysisModel.net_shipment.desc(),
                    ProductLineAnalysisModel.sku.asc(),
                )
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        items = [flatten(row) for row in rows]
        # 多值字段（业务员/订单类型/平台/店铺）存在拼接串里，Python 侧过滤
        for param_key, code in (
            ("salesman", "PRD-18"),
            ("order_type", "PRD-19"),
            ("platform", "PRD-20"),
            ("shop", "PRD-21"),
        ):
            value = getattr(search, param_key, None)
            if value:
                items = [item for item in items if value in str(item.get(code) or "")]
        return {
            "items": items,
            "columns": field_catalog(),
            "total": total,
            "page_no": page_no,
            "page_size": page_size,
            "has_next": page_no * page_size < total,
            "period_value": period,
            "calc_version": version,
            "summary": await self.stats(period),
        }

    async def runs(self, period_value: str | None, limit: int) -> list[ProductLineBuildRunModel]:
        statement = select(ProductLineBuildRunModel).order_by(ProductLineBuildRunModel.id.desc()).limit(limit)
        if period_value:
            statement = statement.where(ProductLineBuildRunModel.period_value == period_value)
        return list((await self.db.execute(statement)).scalars().all())

    async def rebuild(self, period_value: str | None) -> dict[str, Any]:
        period = period_value or await self.latest_period() or datetime.now().strftime("%Y-%m")
        try:
            return await build_period(self.db, period)
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            raise CustomException(msg=f"产品线分析构建失败：{exc}") from exc
