"""MES 订单查询服务：只读订单全链路宽表，取每期最新版本。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.org_person import CRM_SOURCE_TYPE
from app.modules.masterdata.model import SourcePersonModel
from app.modules.order.model import OrderBuildRunModel, OrderFullChainModel

from .schema import MesOrderQueryParam

MES_TRADE_TYPES = ("domestic", "export")


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _like(value: str) -> str:
    return f"%{value.strip()}%"


async def _latest_versions(db: AsyncSession) -> list[tuple[str, int]]:
    """每个期间最新一次成功构建的版本。

    构建批次表只有几百行，比在 20 多万行的宽表上做 ``GROUP BY period_value`` 快得多；
    宽表按期间保留多版本，对外只暴露这里查到的最新版本。
    """
    rows = (
        await db.execute(
            select(
                OrderBuildRunModel.period_value,
                func.max(OrderBuildRunModel.calc_version),
            )
            .where(
                OrderBuildRunModel.status == "success",
                OrderBuildRunModel.is_deleted == False,  # noqa: E712
            )
            .group_by(OrderBuildRunModel.period_value)
        )
    ).all()
    latest = [(str(period), int(version)) for period, version in rows if period and version]
    if latest:
        return latest

    # 兜底：极旧环境没有构建批次记录时，直接从宽表取每期最大版本
    fallback = (
        await db.execute(
            select(
                OrderFullChainModel.period_value,
                func.max(OrderFullChainModel.calc_version),
            )
            .where(OrderFullChainModel.is_deleted == False)  # noqa: E712
            .group_by(OrderFullChainModel.period_value)
        )
    ).all()
    return [(str(period), int(version)) for period, version in fallback if period and version]


async def _person_names(db: AsyncSession) -> dict[str, str]:
    """CRM 人员ID → 当前姓名；每次查询都取最新 ``source_person``。

    负责工程在订单里只存 ``principal_engineering``（人员ID）。MES 返回姓名时
    实时映射到最新人员表，CRM 人员改名/离职后无需等历史订单重算。
    """
    rows = (
        await db.execute(
            select(SourcePersonModel.source_name, SourcePersonModel.raw_json).where(
                SourcePersonModel.source_type == CRM_SOURCE_TYPE,
                SourcePersonModel.is_deleted == False,  # noqa: E712
            )
        )
    ).all()
    names: dict[str, str] = {}
    for source_name, raw in rows:
        raw = raw if isinstance(raw, dict) else {}
        crm_id = raw.get("id")
        name = _text_or_none(source_name)
        if crm_id is not None and name:
            names[str(crm_id)] = name
    return names


def _base_conditions() -> list[Any]:
    return [
        OrderFullChainModel.is_deleted == False,  # noqa: E712
        OrderFullChainModel.trade_type.in_(MES_TRADE_TYPES),
        # 零售单（order_type=3）的 trade_type 也会落 domestic/export，MES 只要内外贸正常订单
        or_(OrderFullChainModel.order_type.is_(None), OrderFullChainModel.order_type != "3"),
        # 2024-10 ~ 2025-06 的零售宽表行 order_type 为空，订单号统一 LS 开头，用前缀兜底排除
        OrderFullChainModel.order_number.notlike("LS%"),
    ]


def _search_conditions(search: MesOrderQueryParam, person_names: dict[str, str]) -> list[Any]:
    conditions: list[Any] = []
    if search.crm_order_no:
        conditions.append(OrderFullChainModel.order_number.like(_like(search.crm_order_no)))
    if search.trade_type:
        conditions.append(OrderFullChainModel.trade_type == search.trade_type)
    if search.customer_name:
        conditions.append(OrderFullChainModel.extra["customer_name"].as_string().like(_like(search.customer_name)))
    if search.engineer_name:
        keyword = search.engineer_name.strip()
        matched_ids = [crm_id for crm_id, name in person_names.items() if keyword in name]
        engineer_conditions = [OrderFullChainModel.extra["engineer_name"].as_string().like(_like(keyword))]
        if matched_ids:
            engineer_conditions.append(OrderFullChainModel.extra["engineer_code"].as_string().in_(matched_ids))
        conditions.append(or_(*engineer_conditions))
    if search.product_series:
        conditions.append(OrderFullChainModel.extra["product_series"].as_string().like(_like(search.product_series)))
    if search.product_model:
        conditions.append(OrderFullChainModel.extra["sku"].as_string().like(_like(search.product_model)))
    if search.product_size:
        conditions.append(OrderFullChainModel.extra["size"].as_string().like(_like(search.product_size)))
    return conditions


def _to_item(row: OrderFullChainModel, person_names: dict[str, str]) -> dict[str, Any]:
    extra = row.extra or {}
    engineer_code = _text_or_none(extra.get("engineer_code"))
    engineer_name = person_names.get(engineer_code) if engineer_code else None
    return {
        "crm_order_no": row.order_number,
        "customer_name": _text_or_none(extra.get("customer_name")),
        "engineer_code": engineer_code,
        "engineer_name": engineer_name or _text_or_none(extra.get("engineer_name")),
        "product_series": _text_or_none(extra.get("product_series")),
        "product_model": _text_or_none(extra.get("sku")),
        "product_size": _text_or_none(extra.get("size")),
        "quantity": float(row.qty) if row.qty is not None else None,
        "trade_type": row.trade_type,
        "order_date": row.order_date,
    }


class MesOrderService:
    """MES 订单只读服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def page(self, search: MesOrderQueryParam, page_no: int = 1, page_size: int = 200) -> dict[str, Any]:
        latest = await _latest_versions(self.db)
        if not latest:
            return {"total": 0, "page_no": page_no, "page_size": page_size, "has_more": False, "items": []}
        person_names = await _person_names(self.db)
        conditions = [
            *_base_conditions(),
            tuple_(OrderFullChainModel.period_value, OrderFullChainModel.calc_version).in_(latest),
            *_search_conditions(search, person_names),
        ]

        total = (await self.db.execute(select(func.count()).select_from(OrderFullChainModel).where(*conditions))).scalar() or 0

        rows = (
            (
                await self.db.execute(
                    select(OrderFullChainModel)
                    .where(*conditions)
                    .order_by(
                        OrderFullChainModel.period_value.desc(),
                        OrderFullChainModel.order_number.desc(),
                    )
                    .offset((page_no - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )

        return {
            "total": int(total),
            "page_no": page_no,
            "page_size": page_size,
            "has_more": page_no * page_size < int(total),
            "items": [_to_item(row, person_names) for row in rows],
        }
