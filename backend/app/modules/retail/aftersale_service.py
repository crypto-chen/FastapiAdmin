"""零售售后/退货退款落库服务。

两个入口共用同一套幂等 upsert：

- 奇门推送（淘系）：``POST /open/v1/retail/aftersales/sync``，免鉴权；
- 聚水潭拉取（非淘系）：``RefundQuery /open/refund/single/query``，定时任务调用。

唯一键 ``as_key = source:as_id``（缺 ``as_id`` 时退化为 ``source:o:outer_as_id``），
上游 ``modified`` 更旧时跳过，内容未变化不计更新；明细按 ``asi_id`` 整单替换。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CustomException
from app.modules.erp.jushuitan.model import JushuitanConnectionModel
from app.modules.erp.jushuitan.service import build_client
from app.modules.openapi.security import CODE_PARAM_INVALID

from .model import RetailAfterSaleItemModel, RetailAfterSaleModel, RetailSyncBatchModel
from .schema import RetailAfterSaleErrorSchema, RetailAfterSaleResultSchema
from .service import RetailSyncService, _bool, _datetime, _decimal, _hash, _int, _text

MAX_AFTER_SALES_PER_REQUEST = 2000
BIZ_TYPE_AFTER_SALE = "after_sale"


def _order_key(value: Any) -> str | None:
    """售后单号统一成字符串；聚水潭返回数字时避免出现 ``123.0``。"""
    text = _text(value, 128)
    if text and text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _period_of(row: dict[str, Any]) -> str:
    for key in ("as_date", "created", "registered", "modified", "confirm_date"):
        moment = _datetime(row.get(key))
        if moment is not None:
            return moment.strftime("%Y-%m")
    return datetime.now().strftime("%Y-%m")


def _actual_refund(row: dict[str, Any]) -> Decimal | None:
    """聚水潭口径：实退 = 运费 + 商品应退 - 补偿 - 优惠。四项全空时返回 None。"""
    parts = [_decimal(row.get(key)) for key in ("freight", "refund", "payment", "free_amount")]
    if all(part is None for part in parts):
        return None
    freight, refund, payment, free_amount = (part or Decimal("0") for part in parts)
    return freight + refund - payment - free_amount


class RetailAfterSaleSyncService:
    """售后单幂等写入，并记录一条同步批次用于重放与审计。"""

    def __init__(self, db: AsyncSession, app_id: str = "public") -> None:
        self.db = db
        self.app_id = app_id

    async def sync(
        self,
        payload: Any,
        request_id: str | None = None,
        source: str | None = None,
        raw_body: bytes | None = None,
    ) -> RetailAfterSaleResultSchema:
        payload = self._alias(payload)
        rows, envelope = RetailSyncService._normalize(payload)
        if not rows:
            raise CustomException(
                msg="未找到售后单数据（支持 after_sales/aftersales/orders/datas/data/裸数组）",
                code=CODE_PARAM_INVALID,
                status_code=400,
            )
        if len(rows) > MAX_AFTER_SALES_PER_REQUEST:
            raise CustomException(
                msg=f"单次推送售后单数超限：{len(rows)} > {MAX_AFTER_SALES_PER_REQUEST}，请分页推送",
                code=CODE_PARAM_INVALID,
                status_code=400,
            )

        source = _text(source, 32) or _text(envelope.get("source"), 32) or "qimen"
        request_id = _text(request_id, 128) or _text(envelope.get("request_id"), 128)
        return await self._write(
            rows=rows,
            source=source,
            request_id=request_id,
            envelope=envelope,
            raw_body=raw_body,
            batch_prefix="as-push",
            replay=True,
        )

    @staticmethod
    def _alias(payload: Any) -> Any:
        """把售后专用包裹键（after_sales/aftersales/refunds）折算成 ``orders``。"""
        if not isinstance(payload, dict):
            return payload
        for key in ("after_sales", "aftersales", "refunds", "refund_list"):
            if key in payload:
                value = payload[key]
                normalized = {k: v for k, v in payload.items() if k != key}
                normalized["orders"] = value
                return normalized
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("after_sales", "aftersales", "refunds", "refund_list"):
                if key in data:
                    inner = dict(data)
                    inner["orders"] = inner.pop(key)
                    normalized = dict(payload)
                    normalized["data"] = inner
                    return normalized
        return payload

    async def pull_refunds(
        self,
        rows: list[dict[str, Any]],
        source: str = "jushuitan",
        request_id: str | None = None,
    ) -> RetailAfterSaleResultSchema:
        """接收集水潭拉取回来的售后单（非淘系），与推送共用落库逻辑。"""
        return await self._write(
            rows=[row for row in rows if isinstance(row, dict)],
            source=source,
            request_id=request_id,
            envelope={"pull": True, "received": len(rows)},
            raw_body=None,
            batch_prefix="as-pull",
            replay=False,
        )

    async def _write(
        self,
        rows: list[dict[str, Any]],
        source: str,
        request_id: str | None,
        envelope: dict[str, Any],
        raw_body: bytes | None,
        batch_prefix: str,
        replay: bool,
    ) -> RetailAfterSaleResultSchema:
        if raw_body is not None:
            payload_hash = hashlib.sha256(raw_body).hexdigest()
        else:
            payload_hash = _hash(envelope)
        request_key = (f"{source}:as:{request_id}" if request_id else payload_hash)[:128]

        if replay:
            existing = await self._find_batch(request_key)
            if existing is not None and isinstance(existing.result, dict):
                data = dict(existing.result)
                data["duplicate"] = True
                return RetailAfterSaleResultSchema.model_validate(data)

        batch_id = f"{batch_prefix}-{datetime.now(UTC):%Y%m%d%H%M%S%f}"
        batch = RetailSyncBatchModel(
            app_id=self.app_id,
            request_key=request_key,
            request_id=request_id,
            source=source,
            status="running",
            payload_hash=payload_hash,
            received_count=len(rows),
            periods=[],
            has_next=False,
            params={"biz_type": BIZ_TYPE_AFTER_SALE, "source": source},
            raw_payload={"biz_type": BIZ_TYPE_AFTER_SALE, "received": len(rows)},
        )
        self.db.add(batch)
        await self.db.flush()

        created = updated = unchanged = stale = failed = item_count = 0
        periods: set[str] = set()
        errors: list[RetailAfterSaleErrorSchema] = []

        for index, row in enumerate(rows):
            try:
                async with self.db.begin_nested():
                    result = await self._upsert(row=row, source=source, batch_id=batch_id)
                periods.add(result["period_value"])
                if result.get("previous_period"):
                    periods.add(result["previous_period"])
                item_count += int(result["item_count"])
                action = result["action"]
                if action == "created":
                    created += 1
                elif action == "updated":
                    updated += 1
                elif action == "unchanged":
                    unchanged += 1
                else:
                    stale += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不阻断整批
                failed += 1
                errors.append(
                    RetailAfterSaleErrorSchema(
                        index=index,
                        as_id=_order_key(row.get("as_id") or row.get("outer_as_id")),
                        reason=str(exc)[:500],
                    )
                )

        status = "success" if failed == 0 else ("partial" if failed < len(rows) else "failed")
        batch.status = status
        batch.created_count = created
        batch.updated_count = updated
        batch.unchanged_count = unchanged
        batch.stale_count = stale
        batch.failed_count = failed
        batch.item_count = item_count
        batch.periods = sorted(periods)
        batch.errors = [item.model_dump() for item in errors[:100]]

        result = RetailAfterSaleResultSchema(
            batch_id=batch_id,
            request_id=request_id,
            received=len(rows),
            created=created,
            updated=updated,
            unchanged=unchanged,
            stale=stale,
            failed=failed,
            item_count=item_count,
            periods=sorted(periods),
            errors=errors[:100],
        )
        batch.result = result.model_dump()
        await self.db.flush()
        return result

    async def _find_batch(self, request_key: str) -> RetailSyncBatchModel | None:
        return (
            (
                await self.db.execute(
                    select(RetailSyncBatchModel).where(
                        RetailSyncBatchModel.app_id == self.app_id,
                        RetailSyncBatchModel.request_key == request_key,
                        RetailSyncBatchModel.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _upsert(
        self,
        row: dict[str, Any],
        source: str,
        batch_id: str,
    ) -> dict[str, Any]:
        as_id = _order_key(row.get("as_id"))
        outer_as_id = _order_key(row.get("outer_as_id"))
        if as_id:
            as_key = f"{source}:{as_id}"[:180]
        elif outer_as_id:
            as_key = f"{source}:o:{outer_as_id}"[:180]
        else:
            raise ValueError("缺少 as_id/outer_as_id，无法确定售后单唯一键")

        content_hash = _hash(row)
        modified_time = _datetime(row.get("modified") or row.get("modified_time"))
        period_value = _period_of(row)
        items = row.get("items") if isinstance(row.get("items"), list) else []

        existing = (
            (
                await self.db.execute(
                    select(RetailAfterSaleModel).where(
                        RetailAfterSaleModel.as_key == as_key,
                        RetailAfterSaleModel.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if (
                existing.modified_time is not None
                and modified_time is not None
                and modified_time < existing.modified_time
            ):
                return {"action": "stale", "period_value": existing.period_value, "item_count": 0}
            if existing.content_hash == content_hash:
                return {"action": "unchanged", "period_value": existing.period_value, "item_count": 0}
            action = "updated"
            target = existing
            previous_period = (
                existing.period_value if existing.period_value != period_value else None
            )
        else:
            action = "created"
            previous_period = None
            target = RetailAfterSaleModel(
                as_key=as_key,
                content_hash=content_hash,
                period_value=period_value,
                last_batch_id=batch_id,
            )
            self.db.add(target)
            await self.db.flush()

        target.source = source
        target.as_id = as_id
        target.outer_as_id = outer_as_id
        target.o_id = _order_key(row.get("o_id"))
        target.so_id = _order_key(row.get("so_id") or row.get("outer_so_id") or row.get("raw_so_id"))
        target.shop_id = _int(row.get("shop_id"), 0)
        target.shop_name = _text(row.get("shop_name"), 128)
        target.shop_site = _text(row.get("shop_site") or row.get("platform"), 64)
        target.type = _text(row.get("type"), 32)
        target.status = _text(row.get("status"), 32)
        target.shop_status = _text(row.get("shop_status"), 64)
        target.good_status = _text(row.get("good_status"), 32)
        target.order_status = _text(row.get("order_status"), 32)
        target.as_date = _datetime(row.get("as_date"))
        target.registered_time = _datetime(row.get("created") or row.get("registered"))
        target.modified_time = modified_time
        target.confirm_date = _datetime(row.get("confirm_date"))
        target.period_value = period_value
        target.refund = _decimal(row.get("refund"))
        target.payment = _decimal(row.get("payment"))
        target.free_amount = _decimal(row.get("free_amount"))
        target.freight = _decimal(row.get("freight"))
        target.actual_refund = _actual_refund(row)
        target.buyer_apply_refund = _decimal(row.get("buyer_apply_refund"))
        target.receive_refund = _decimal(row.get("receive_refund"))
        target.seller_real_refund = _decimal(row.get("seller_real_refund"))
        target.buyer_paid_amount = _decimal(row.get("buyer_paid_amount"))
        target.seller_income_amount = _decimal(row.get("seller_income_amount"))
        target.platform_promotion = _decimal(row.get("platform_promotion"))
        target.platform_free_amount = _decimal(row.get("platform_free_amount"))
        target.government_free_amount = _decimal(row.get("government_free_amount"))
        target.warehouse = _text(row.get("warehouse"), 128)
        target.wms_co_id = _text(row.get("wms_co_id"), 64)
        target.l_id = _text(row.get("l_id"), 64)
        target.logistics_company = _text(row.get("logistics_company"), 128)
        target.remark = _text(row.get("remark"), 2000)
        target.result = _text(row.get("result"), 2000)
        target.node = _text(row.get("node"), 2000)
        target.currency = _text(row.get("currency"), 16)
        target.content_hash = content_hash
        target.last_batch_id = batch_id
        target.raw = row

        await self.db.execute(
            delete(RetailAfterSaleItemModel).where(
                RetailAfterSaleItemModel.after_sale_id == target.id
            )
        )
        seen_lines: set[str] = set()
        saved_items = 0
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            line_key = _text(item.get("asi_id"), 128) or _hash(item)[:32]
            if line_key in seen_lines:
                line_key = f"{line_key}-{index}"[:128]
            seen_lines.add(line_key)
            self.db.add(
                RetailAfterSaleItemModel(
                    after_sale_id=target.id,
                    line_key=line_key,
                    asi_id=_text(item.get("asi_id"), 64),
                    sku_id=_text(item.get("sku_id"), 64),
                    i_id=_text(item.get("i_id"), 64),
                    name=_text(item.get("name"), 512),
                    properties_value=_text(item.get("properties_value"), 512),
                    qty=_decimal(item.get("qty")),
                    r_qty=_decimal(item.get("r_qty")),
                    defective_qty=_decimal(item.get("defective_qty")),
                    price=_decimal(item.get("price")),
                    amount=_decimal(item.get("amount")),
                    shop_amount=_decimal(item.get("shop_amount")),
                    buyer_paid_amount=_decimal(item.get("buyer_paid_amount")),
                    seller_income_amount=_decimal(item.get("seller_income_amount")),
                    type=_text(item.get("type"), 32),
                    is_gift=_bool(item.get("is_gift")),
                    sku_type=_text(item.get("sku_type"), 32),
                    combine_sku_id=_text(item.get("combine_sku_id"), 64),
                    outer_oi_id=_text(item.get("outer_oi_id"), 64),
                    raw_so_id=_text(item.get("raw_so_id"), 64),
                    receive_date=_datetime(item.get("receive_date")),
                    raw=item,
                )
            )
            saved_items += 1
        target.item_count = saved_items
        await self.db.flush()
        return {
            "action": action,
            "period_value": period_value,
            "previous_period": previous_period,
            "item_count": saved_items,
        }


async def pull_jushuitan_refunds(
    db: AsyncSession,
    begin: datetime,
    end: datetime,
    connection_id: int | None = None,
    max_rows: int | None = None,
    source: str = "jushuitan",
) -> RetailAfterSaleResultSchema:
    """从聚水潭拉取非淘系售后单并落库（定时任务与管理端手动同步共用）。

    聚水潭售后接口不返回淘系/拼多多售后单（拼多多仅近 3 个月），淘系走奇门推送。
    """
    if connection_id:
        connection = await db.get(JushuitanConnectionModel, int(connection_id))
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

    limit = int(max_rows or 5000)
    rows: list[dict[str, Any]] = []
    async with build_client(connection) as client:
        async for row in client.iter_refunds(begin, end, date_type=0):
            rows.append(row)
            if len(rows) >= limit:
                break

    request_id = f"jst-as-{begin:%Y%m%d%H%M}-{end:%Y%m%d%H%M}"
    result = await RetailAfterSaleSyncService(db, app_id="jushuitan").pull_refunds(
        rows, source=source, request_id=request_id
    )
    return result
