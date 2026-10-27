"""零售店铺/平台主数据同步。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.erp.jushuitan.model import JushuitanConnectionModel
from app.modules.erp.jushuitan.service import build_client

from .model import RetailShopModel


def _text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] if text else None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RetailShopService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sync_shops(self, shops: list[dict[str, Any]], source: str = "jushuitan") -> dict[str, Any]:
        """按 ``source + shop_id`` upsert 店铺，返回处理计数。"""
        created = updated = failed = 0
        errors: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for index, raw in enumerate(shops):
            if not isinstance(raw, dict):
                failed += 1
                errors.append({"index": index, "reason": "店铺不是对象"})
                continue
            shop_id = _int(raw.get("shop_id"))
            if shop_id is None:
                failed += 1
                errors.append({"index": index, "reason": "缺少 shop_id"})
                continue
            try:
                async with self.db.begin_nested():
                    row = (
                        await self.db.execute(
                            select(RetailShopModel).where(
                                RetailShopModel.source == source,
                                RetailShopModel.shop_id == shop_id,
                            )
                        )
                    ).scalars().first()
                    if row is None:
                        row = RetailShopModel(source=source, shop_id=shop_id)
                        self.db.add(row)
                        created += 1
                    else:
                        updated += 1
                    row.shop_name = _text(raw.get("shop_name"), 128)
                    row.shop_site = _text(raw.get("shop_site"), 64)
                    row.platform_shop_name = _text(raw.get("platform_shop_name"), 128)
                    row.co_id = _text(raw.get("co_id"), 64)
                    row.nick = _text(raw.get("nick"), 128)
                    row.session_status = _int(raw.get("session_status"))
                    row.session_expired = _text(raw.get("session_expired"), 64)
                    row.group_id = _int(raw.get("group_id"))
                    row.group_name = _text(raw.get("group_name"), 128)
                    row.shop_url = _text(raw.get("shop_url"), 255)
                    row.short_name = _text(raw.get("short_name"), 128)
                    row.synced_at = now
                    row.raw = raw
            except Exception as exc:  # noqa: BLE001
                failed += 1
                errors.append({"index": index, "shop_id": shop_id, "reason": str(exc)[:300]})
        await self.db.flush()
        return {
            "received": len(shops),
            "created": created,
            "updated": updated,
            "failed": failed,
            "errors": errors[:100],
        }


async def sync_jushuitan_shops(
    db: AsyncSession,
    connection_id: int | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """从聚水潭拉取店铺并写入 retail_shop（供定时任务/管理端按钮共用）。"""
    if connection_id:
        connection = await db.get(JushuitanConnectionModel, int(connection_id))
    elif name:
        connection = (
            await db.execute(
                select(JushuitanConnectionModel).where(JushuitanConnectionModel.name == name)
            )
        ).scalars().first()
    else:
        connection = (
            await db.execute(
                select(JushuitanConnectionModel)
                .where(JushuitanConnectionModel.status == 0)
                .order_by(JushuitanConnectionModel.id.asc())
                .limit(1)
            )
        ).scalars().first()
    if connection is None or connection.status == 1:
        raise ValueError("没有启用的聚水潭连接")

    async with build_client(connection) as client:
        shops = [row async for row in client.iter_shops()]
    result = await RetailShopService(db).sync_shops(shops, source="jushuitan")
    result["connection_id"] = connection.id
    result["connection_name"] = connection.name
    return result
