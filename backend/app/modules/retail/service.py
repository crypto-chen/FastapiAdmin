"""零售数据推送落库服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.setting import settings
from app.core.exceptions import CustomException
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel
from app.modules.openapi.security import CODE_PARAM_INVALID

from .model import RetailOrderItemModel, RetailOrderModel, RetailSyncBatchModel
from .schema import RetailSyncErrorSchema, RetailSyncPayload, RetailSyncResultSchema

MAX_ORDERS_PER_REQUEST = 2000
MAX_RAW_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 20 * 1024 * 1024
DEFAULT_RETAIL_PUSH_JOB_NAME = "零售数据-外部推送"


def _text(value: Any, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length] if max_length else text


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ")
    for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _period_of(order: dict[str, Any]) -> str:
    for key in ("io_date", "pay_date", "order_date", "created", "modified"):
        moment = _datetime(order.get(key))
        if moment is not None:
            return moment.strftime("%Y-%m")
    return datetime.now().strftime("%Y-%m")


class RetailSyncService:
    """接收外部推送的零售订单，幂等 upsert，并可回放到同步批次。"""

    def __init__(
        self,
        db: AsyncSession,
        app_id: str = "public",
        client_id: int | None = None,
        retail_sync_job_id: int | None = None,
    ) -> None:
        self.db = db
        self.app_id = app_id
        self.client_id = client_id
        self.retail_sync_job_id = retail_sync_job_id

    async def sync(
        self,
        payload: RetailSyncPayload | list[dict[str, Any]],
        request_id: str | None = None,
        raw_body: bytes | None = None,
    ) -> RetailSyncResultSchema:
        orders, envelope = self._normalize(payload)
        if not orders:
            raise CustomException(
                msg="未找到订单数据（支持 orders/datas/data/裸数组）",
                code=CODE_PARAM_INVALID,
                status_code=400,
            )
        if len(orders) > MAX_ORDERS_PER_REQUEST:
            raise CustomException(
                msg=f"单次推送订单数超限：{len(orders)} > {MAX_ORDERS_PER_REQUEST}，请分页推送",
                code=CODE_PARAM_INVALID,
                status_code=400,
            )

        source = _text(envelope.get("source"), 32) or "qimen"
        request_id = _text(request_id, 128) or _text(envelope.get("request_id"), 128)
        if raw_body is not None:
            payload_hash = hashlib.sha256(raw_body).hexdigest()
        else:
            payload_hash = hashlib.sha256(
                json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        request_key = (f"{source}:{request_id}" if request_id else payload_hash)[:128]

        existing = await self._find_batch(request_key)
        if existing is not None:
            return self._replay(existing)

        if len(raw_body or b"") > MAX_RAW_PAYLOAD_BYTES:
            raw_payload: dict[str, Any] = {"_omitted": True, "size": len(raw_body or b"")}
        elif envelope:
            raw_payload = envelope
        else:
            raw_payload = {"orders": orders}

        batch_id = f"push-{datetime.now(UTC):%Y%m%d%H%M%S%f}"
        batch = RetailSyncBatchModel(
            app_id=self.app_id,
            client_id=self.client_id,
            request_key=request_key,
            request_id=request_id,
            source=source,
            status="running",
            payload_hash=payload_hash,
            received_count=len(orders),
            periods=[],
            page_index=_int(envelope.get("page_index"), 0) or None,
            page_size=_int(envelope.get("page_size"), 0) or None,
            has_next=bool(envelope.get("has_next")),
            params=envelope.get("params") if isinstance(envelope.get("params"), dict) else None,
            raw_payload=raw_payload,
        )
        self.db.add(batch)
        await self.db.flush()

        created = updated = unchanged = stale = failed = item_count = 0
        periods: set[str] = set()
        errors: list[RetailSyncErrorSchema] = []

        for index, order in enumerate(orders):
            if not isinstance(order, dict):
                failed += 1
                errors.append(RetailSyncErrorSchema(index=index, reason="订单不是对象"))
                continue
            try:
                # 每单一个 SAVEPOINT：单条写库失败只回滚该单，不拖垮整批事务
                async with self.db.begin_nested():
                    result = await self._upsert_order(
                        order=order,
                        source=source,
                        batch_id=batch_id,
                    )
                periods.add(result["period_value"])
                if result.get("previous_period"):
                    periods.add(result["previous_period"])
                item_count += int(result["item_count"])
                if result["action"] == "created":
                    created += 1
                elif result["action"] == "updated":
                    updated += 1
                elif result["action"] == "unchanged":
                    unchanged += 1
                else:
                    stale += 1
            except Exception as exc:  # noqa: BLE001 - 单条订单失败不阻断整批
                failed += 1
                order_id = _text(order.get("so_id") or order.get("o_id"), 64)
                errors.append(
                    RetailSyncErrorSchema(index=index, order_id=order_id, reason=str(exc)[:500])
                )

        metric_sync: list[dict[str, Any]] = []
        job_id = await self._resolve_job_id()
        if job_id:
            for period in sorted(periods):
                try:
                    async with self.db.begin_nested():
                        metric_sync.append(
                            await self._publish_period(int(job_id), period, source, batch_id)
                        )
                except Exception as exc:  # noqa: BLE001 - 回放失败不应回滚已入库的零售数据
                    metric_sync.append(
                        {
                            "period_value": period,
                            "status": "failed",
                            "reason": str(exc)[:300],
                        }
                    )

        status = "success" if failed == 0 else ("partial" if failed < len(orders) else "failed")
        batch.status = status
        batch.created_count = created
        batch.updated_count = updated
        batch.unchanged_count = unchanged
        batch.stale_count = stale
        batch.failed_count = failed
        batch.item_count = item_count
        batch.periods = sorted(periods)
        batch.errors = [item.model_dump() for item in errors[:100]]

        result = RetailSyncResultSchema(
            batch_id=batch_id,
            request_id=request_id,
            received=len(orders),
            created=created,
            updated=updated,
            unchanged=unchanged,
            stale=stale,
            failed=failed,
            item_count=item_count,
            periods=sorted(periods),
            has_next=bool(envelope.get("has_next")),
            errors=errors[:100],
            metric_sync=metric_sync,
        )
        batch.result = result.model_dump()
        await self.db.flush()
        return result

    @staticmethod
    def _normalize(
        payload: RetailSyncPayload | list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], {}
        envelope = payload.model_dump(exclude_none=True)
        orders = RetailSyncService._as_orders(envelope.get("orders"))
        if not orders:
            orders = RetailSyncService._as_orders(envelope.get("datas"))
        if not orders:
            data = envelope.get("data")
            orders = RetailSyncService._as_orders(data)
            if isinstance(data, dict):
                for key in ("params", "page_index", "page_size", "has_next", "data_count", "source"):
                    if key in data and key not in envelope:
                        envelope[key] = data[key]
        return [item for item in orders if isinstance(item, dict)], envelope

    @staticmethod
    def _as_orders(value: Any) -> list[dict[str, Any]]:
        """兼容数组、单个订单对象和低代码平台传来的 JSON 字符串。"""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                value = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("orders", "datas", "data"):
                nested = value.get(key)
                if isinstance(nested, (list, str)):
                    parsed = RetailSyncService._as_orders(nested)
                    if parsed:
                        return parsed
            if any(key in value for key in ("so_id", "o_id", "outer_so_id", "raw_so_id")):
                return [value]
        return []

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

    async def _resolve_job_id(self) -> int | None:
        """确定回放任务：显式配置优先，否则按默认任务名自动查找。"""
        if self.retail_sync_job_id:
            return int(self.retail_sync_job_id)
        configured = getattr(settings, "RETAIL_SYNC_JOB_ID", None)
        if configured:
            return int(configured)
        job_id = (
            await self.db.execute(
                select(MetaSyncJobModel.id)
                .where(
                    MetaSyncJobModel.name == DEFAULT_RETAIL_PUSH_JOB_NAME,
                    MetaSyncJobModel.status == 0,
                    MetaSyncJobModel.is_deleted == False,  # noqa: E712
                )
                .order_by(MetaSyncJobModel.id.desc())
                .limit(1)
            )
        ).scalars().first()
        return int(job_id) if job_id else None

    @staticmethod
    def _replay(batch: RetailSyncBatchModel) -> RetailSyncResultSchema:
        if isinstance(batch.result, dict) and batch.result.get("batch_id"):
            data = dict(batch.result)
            data["duplicate"] = True
            return RetailSyncResultSchema.model_validate(data)
        return RetailSyncResultSchema(
            batch_id=batch.request_key,
            request_id=batch.request_id,
            duplicate=True,
            received=batch.received_count,
            created=batch.created_count,
            updated=batch.updated_count,
            unchanged=batch.unchanged_count,
            stale=batch.stale_count,
            failed=batch.failed_count,
            item_count=batch.item_count,
            periods=list(batch.periods or []),
            has_next=bool(batch.has_next),
            errors=[RetailSyncErrorSchema.model_validate(item) for item in (batch.errors or [])],
        )

    async def _upsert_order(
        self,
        order: dict[str, Any],
        source: str,
        batch_id: str,
    ) -> dict[str, Any]:
        so_id = _text(order.get("so_id") or order.get("outer_so_id") or order.get("raw_so_id"), 64)
        o_id = _text(order.get("o_id"), 64)
        business_id = so_id or o_id
        if not business_id:
            raise ValueError("缺少 so_id/o_id，无法确定订单唯一键")

        shop_id = _int(order.get("shop_id"), 0)
        order_key = f"{source}:{shop_id}:{business_id}"[:160]
        content_hash = _hash(order)
        modified_time = _datetime(order.get("modified") or order.get("modified_time"))
        period_value = _period_of(order)
        items = order.get("items") if isinstance(order.get("items"), list) else []

        existing = (
            (
                await self.db.execute(
                    select(RetailOrderModel).where(
                        RetailOrderModel.order_key == order_key,
                        RetailOrderModel.is_deleted == False,  # noqa: E712
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
                return {
                    "action": "stale",
                    "period_value": existing.period_value,
                    "item_count": 0,
                }
            if existing.content_hash == content_hash:
                return {
                    "action": "unchanged",
                    "period_value": existing.period_value,
                    "item_count": 0,
                }
            action = "updated"
            target = existing
            previous_period = existing.period_value if existing.period_value != period_value else None
        else:
            action = "created"
            previous_period = None
            target = RetailOrderModel(
                order_key=order_key,
                first_batch_id=batch_id,
                last_batch_id=batch_id,
                content_hash=content_hash,
                period_value=period_value,
            )
            self.db.add(target)
            await self.db.flush()

        target.source = source
        target.shop_id = shop_id
        target.so_id = so_id
        target.o_id = o_id
        target.co_id = _text(order.get("co_id"), 64)
        target.status = _text(order.get("status"), 32)
        target.order_from = _text(order.get("order_from"), 32)
        target.shop_name = _text(order.get("shop_name"), 128)
        target.shop_site = _text(order.get("shop_site"), 64)
        target.buyer_id = _text(order.get("buyer_id"), 64)
        target.buyer_nick = _text(order.get("shop_buyer_id"), 128)
        target.order_date = _datetime(order.get("order_date"))
        target.pay_date = _datetime(order.get("pay_date"))
        target.modified_time = modified_time
        target.plan_delivery_date = _datetime(order.get("plan_delivery_date"))
        target.period_value = period_value
        target.paid_amount = _decimal(order.get("paid_amount"))
        target.pay_amount = _decimal(order.get("pay_amount"))
        target.buyer_paid_amount = _decimal(order.get("buyer_paid_amount"))
        target.seller_income_amount = _decimal(order.get("seller_income_amount"))
        target.freight = _decimal(order.get("freight"))
        target.free_amount = _decimal(order.get("free_amount"))
        target.receiver_state = _text(order.get("receiver_state"), 64)
        target.receiver_city = _text(order.get("receiver_city"), 64)
        target.receiver_district = _text(order.get("receiver_district"), 64)
        target.receiver_town = _text(order.get("receiver_town"), 64)
        target.remark = _text(order.get("remark"), 2000)
        target.seller_flag = _text(order.get("seller_flag"), 32)
        target.item_count = len(items)
        target.content_hash = content_hash
        target.last_batch_id = batch_id
        target.raw = order

        await self.db.execute(
            delete(RetailOrderItemModel).where(RetailOrderItemModel.order_id == target.id)
        )
        seen_lines: set[str] = set()
        saved_items = 0
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            line_key = _text(item.get("oi_id"), 128) or _hash(item)[:32]
            if line_key in seen_lines:
                line_key = f"{line_key}-{index}"[:128]
            seen_lines.add(line_key)
            self.db.add(
                RetailOrderItemModel(
                    order_id=target.id,
                    line_key=line_key,
                    oi_id=_text(item.get("oi_id"), 64),
                    sku_id=_text(item.get("sku_id"), 64),
                    i_id=_text(item.get("i_id"), 64),
                    name=_text(item.get("name"), 512),
                    properties_value=_text(item.get("properties_value"), 512),
                    qty=_decimal(item.get("qty")),
                    price=_decimal(item.get("price")),
                    base_price=_decimal(item.get("base_price")),
                    amount=_decimal(item.get("amount")),
                    buyer_paid_amount=_decimal(item.get("buyer_paid_amount")),
                    seller_income_amount=_decimal(item.get("seller_income_amount")),
                    item_pay_amount=_decimal(item.get("item_pay_amount")),
                    item_status=_text(item.get("item_status"), 32),
                    refund_status=_text(item.get("refund_status"), 32),
                    is_gift=_bool(item.get("is_gift")),
                    src_combine_sku_id=_text(item.get("src_combine_sku_id"), 64),
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

    async def _publish_period(
        self,
        job_id: int,
        period_value: str,
        source: str,
        batch_id: str,
    ) -> dict[str, Any]:
        """把该期间已落库的订单回放成一条 meta_sync_run，供现有指标引擎取数。"""
        job = await self.db.get(MetaSyncJobModel, job_id)
        if job is None or job.is_deleted:
            return {"period_value": period_value, "status": "skipped", "reason": "同步任务不存在"}
        rows = (
            (
                await self.db.execute(
                    select(RetailOrderModel.raw)
                    .where(
                        RetailOrderModel.source == source,
                        RetailOrderModel.period_value == period_value,
                        RetailOrderModel.is_deleted == False,  # noqa: E712
                    )
                    .order_by(RetailOrderModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
        datas = [row for row in rows if isinstance(row, dict)]
        run = MetaSyncRunModel(
            job_id=job_id,
            batch_id=f"{batch_id}-{period_value}"[:64],
            period_value=period_value,
            status="success",
            row_count=len(datas),
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            rows_json={"datas": datas, "data_count": len(datas), "source": "retail_push"},
        )
        self.db.add(run)
        await self.db.flush()
        return {
            "period_value": period_value,
            "status": "published",
            "run_id": run.id,
            "row_count": len(datas),
        }
