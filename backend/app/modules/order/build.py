"""订单全链路构建：把各来源批次关联成一行一单的宽表。

关联链路（详见 ``docs/订单全链路数据方案.md`` §5）：

```
orderAnalyze(内贸/外贸) ── 订单主表（一行一单）
    ├─ orderShipments 按 order_number        → 出货未税
    ├─ PRD_MO 按 FSaleOrderNo(取前两段)      → 生产工单/入库数量/生产周期/实际交期
    ├─ getReturnOrderDetail 按 number        → 退货退款
    └─ getCusotmerList                       → 客户名称
```

幂等：同一期间每次构建都写新的 ``calc_version``，不覆盖历史版本。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel
from app.modules.metadata.sync import extract_payload_rows

# 业务员姓名沿用指标引擎的人员映射链（CRM create_id → source_person → 工号 → master_person），
# 保证订单全链路与业务员指标口径一致，避免两处各维护一套映射。
from app.modules.metric.engine import _load_person_index

from .fields import (
    DATETIME_KEYS,
    INTAKE_KEYS_DOMESTIC,
    INTAKE_KEYS_EXPORT,
    MATERIAL_COST_KEYS,
    MONEY_SCALE,
    PROCESS_COST_KEYS,
    RATE_SCALE,
    SOURCE_KEYS,
)
from .model import OrderBuildRunModel, OrderFullChainModel

logger = logging.getLogger(__name__)

ORDER_OBJECT_DOMESTIC = "/hs/order/orderAnalyze?type=1"
ORDER_OBJECT_EXPORT = "/hs/order/orderAnalyze?type=2"
SHIPMENT_OBJECT_DOMESTIC = "/hs/order/orderShipments?type=1"
SHIPMENT_OBJECT_EXPORT = "/hs/order/orderShipments?type=2"
# 发货明细（发货时间口径，2026-10-16 接入）：按 order_id 关联，用于出货数量
SHIPMENT_DETAIL_OBJECT = "/hs/shipments/getShipmentsDetail"
CUSTOMER_OBJECT = "/hs/customer/getCusotmerList"
PRODUCT_CATEGORY_OBJECT = "/hs/product/getProductCategory"
PRODUCT_MODEL_OBJECT = "/hs/product/getProductModel"
BASE_CATEGORY_OBJECT = "/hs/base/getBaseCategoryList"
RETURN_OBJECT = "/hs/getReturnOrderDetail"
MO_OBJECT = "PRD_MO"

TRADE_DOMESTIC = "domestic"
TRADE_EXPORT = "export"

# 订单类型：CRM order_type 1=批量 2=打样 3=零售（宽表展示名称，编码另存 order_type_code）
ORDER_TYPE_NAMES = {"1": "批量", "2": "打样", "3": "零售"}
# 新老客户：CRM is_new 1=新客户 2=老客户（宽表展示名称，编码另存 is_new_code）
IS_NEW_NAMES = {"1": "新客户", "2": "老客户"}

# 发货/退货等「接单之后才发生」的明细，构建某期间时要往后看多少期。
# 例：DY202609-03163 是 9 月接单、10 月才发货，只看 9 月批次会取不到出货数据。
FORWARD_PERIODS = 12


# --------------------------------------------------------------------------- #
# 取值工具
# --------------------------------------------------------------------------- #
def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == "-"


def pick(row: dict, keys: list[str]) -> Any:
    """按顺序取第一个非空值。"""
    for key in keys:
        value = row.get(key)
        if not _is_empty(value):
            return value
    return None


def to_number(value: Any) -> float | None:
    if _is_empty(value):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def to_datetime(value: Any) -> datetime | None:
    """兼容 unix 秒、``YYYY-MM-DD``、``YYYY-MM-DD HH:MM:SS``、ISO 串。"""
    if _is_empty(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return to_datetime(int(text))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt) + 4].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    parsed = to_datetime(value)
    return parsed.date() if parsed else None


def money(value: float | None) -> float | None:
    return None if value is None else round(float(value), MONEY_SCALE)


def base_order_number(value: Any) -> str:
    """生产订单的需求单据 → CRM 订单号（去掉 ``-物料`` 后缀）。"""
    text = str(value or "").strip()
    parts = text.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else text


def days_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 86400, 4)


def pick_inbound_qty(mo_rows: list[dict]) -> tuple[float | None, bool]:
    """从生产订单分录里取「这张 CRM 订单」的入库数量。

    一张生产订单通常含多条分录（1 条半成品 ``C.`` + 若干成品 ``BCP`` 部件），
    把各分录入库数直接相加会把部件也算进去（订单 2 台会算成 22 台）。取数优先级：

    1. 含 ``C.`` 的半成品分录（整机，数量与订单一致）；
    2. 只有一条分录时直接取该分录；
    3. 多条分录但各分录入库数一致时取该值；
    4. 否则取入库数最大的一条（少数 AF/批量单），返回 ``approximate=True`` 供打标记。
    """
    if not mo_rows:
        return None, False
    c_entries = [
        row for row in mo_rows if str(row.get("FMaterialId.FNumber") or "").startswith("C.")
    ]
    if c_entries:
        total = sum(to_number(row.get("FStockInQuaQty")) or 0.0 for row in c_entries)
        return total, False
    if len(mo_rows) == 1:
        return to_number(mo_rows[0].get("FStockInQuaQty")) or 0.0, False
    values = [to_number(row.get("FStockInQuaQty")) or 0.0 for row in mo_rows]
    if len(set(values)) == 1:
        return values[0], False
    return max(values), True


def jsonable(value: Any) -> Any:
    """把 date/datetime/Decimal 转成可写 JSON 的形态。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


# --------------------------------------------------------------------------- #
# 取数：按来源对象编码 + 期间取最近一次成功批次
# --------------------------------------------------------------------------- #
async def latest_batch(db: AsyncSession, object_code: str, period_value: str | None) -> tuple[str | None, list]:
    """按来源对象编码取该期间最近一次成功批次的原始行。"""
    object_id = (
        await db.execute(select(SourceObjectModel.id).where(SourceObjectModel.code == object_code))
    ).scalar()
    if object_id is None:
        return None, []
    conditions = [
        MetaSyncJobModel.source_object_id == object_id,
        MetaSyncRunModel.status == "success",
    ]
    if period_value:
        conditions.append(MetaSyncRunModel.period_value == period_value)
    # 注意：``rows_json`` 单批可达数 MB，先排序取 id 再按主键取大字段，
    # 避免 MySQL ``Out of sort memory``（ORDER BY 带上大 JSON 列会爆排序缓冲）。
    run_id = (
        await db.execute(
            select(MetaSyncRunModel.id)
            .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
            .where(*conditions)
            .order_by(MetaSyncRunModel.id.desc())
            .limit(1)
        )
    ).scalar()
    if run_id is None:
        return None, []
    row = (
        await db.execute(
            select(MetaSyncRunModel.batch_id, MetaSyncRunModel.rows_json).where(MetaSyncRunModel.id == run_id)
        )
    ).first()
    if row is None:
        return None, []
    return row[0], extract_payload_rows(row[1] or {})


async def merged_order_rows(db: AsyncSession, object_code: str, period_value: str) -> tuple[list[str], list[dict]]:
    """把该期间**所有**成功批次按订单号合并（新批次覆盖非空字段）。

    用途：CRM 2026-10-13 改版后，新批次带回成本字段但丢掉了业务属性；
    旧批次有业务属性但没有成本。两批合并才能同时拿到（方案 §4.2 的兜底设计）。
    """
    object_id = (
        await db.execute(select(SourceObjectModel.id).where(SourceObjectModel.code == object_code))
    ).scalar()
    if object_id is None:
        return [], []
    run_ids = (
        await db.execute(
            select(MetaSyncRunModel.id)
            .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
            .where(
                MetaSyncJobModel.source_object_id == object_id,
                MetaSyncRunModel.status == "success",
                MetaSyncRunModel.period_value == period_value,
            )
            .order_by(MetaSyncRunModel.id.asc())
        )
    ).scalars().all()
    batch_ids: list[str] = []
    merged: dict[str, dict] = {}
    for run_id in run_ids:
        row = (
            await db.execute(
                select(MetaSyncRunModel.batch_id, MetaSyncRunModel.rows_json).where(MetaSyncRunModel.id == run_id)
            )
        ).first()
        if row is None:
            continue
        if row[0]:
            batch_ids.append(row[0])
        for item in extract_payload_rows(row[1] or {}):
            number = str(item.get("number") or "").strip()
            if not number:
                continue
            target = merged.setdefault(number, {})
            for key, value in item.items():
                if not _is_empty(value):
                    target[key] = value
    return batch_ids, list(merged.values())


async def forward_rows(
    db: AsyncSession, object_code: str, from_period: str, max_periods: int = FORWARD_PERIODS
) -> list[dict]:
    """取「该期间及之后」的明细行（每个期间只取最新一次成功批次，避免重复计数）。

    用于发货 / 退货这类**发生在接单之后**的明细：9 月接单的单可能 10 月才发货，
    只读 9 月的批次会漏掉出货数据。期间取到已存在的最后一个月为止（未来月份还没数据）。
    """
    object_id = (
        await db.execute(select(SourceObjectModel.id).where(SourceObjectModel.code == object_code))
    ).scalar()
    if object_id is None:
        return []
    latest_per_period = (
        select(func.max(MetaSyncRunModel.id).label("run_id"))
        .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
        .where(
            MetaSyncJobModel.source_object_id == object_id,
            MetaSyncRunModel.status == "success",
            MetaSyncRunModel.period_value.is_not(None),
            MetaSyncRunModel.period_value >= from_period,
        )
        .group_by(MetaSyncRunModel.period_value)
        .order_by(MetaSyncRunModel.period_value)
        .limit(max_periods)
        .subquery()
    )
    run_ids = (
        await db.execute(select(latest_per_period.c.run_id).order_by(latest_per_period.c.run_id))
    ).scalars().all()
    rows: list[dict] = []
    for run_id in run_ids:
        payload = (
            await db.execute(select(MetaSyncRunModel.rows_json).where(MetaSyncRunModel.id == run_id))
        ).scalar()
        rows.extend(extract_payload_rows(payload or {}))
    return rows


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #
async def next_calc_version(db: AsyncSession, period_value: str) -> int:
    current = (
        await db.execute(
            select(func.max(OrderFullChainModel.calc_version)).where(
                OrderFullChainModel.period_value == period_value
            )
        )
    ).scalar()
    return int(current or 0) + 1


async def build_period(db: AsyncSession, period_value: str, prune_versions: int = 3) -> dict:
    """构建一个期间的订单全链路宽表，返回统计结果。"""
    run = OrderBuildRunModel(period_value=period_value, status="running", started_at=datetime.now(UTC))
    db.add(run)
    await db.flush()

    try:
        batches: dict[str, Any] = {}
        # 订单用一个期间内的全部批次合并（旧批次业务属性 + 新批次成本字段）
        domestic_batches, order_rows_domestic = await merged_order_rows(db, ORDER_OBJECT_DOMESTIC, period_value)
        export_batches, order_rows_export = await merged_order_rows(db, ORDER_OBJECT_EXPORT, period_value)
        batches["order_domestic"] = domestic_batches
        batches["order_export"] = export_batches
        if not order_rows_domestic and not order_rows_export:
            raise ValueError(f"期间 {period_value} 没有 CRM 订单明细批次（orderAnalyze 内贸/外贸）")

        # 发货明细按「该期间及之后」取：跨月发货（9 月接单、10 月发货）才算得到
        shipment_rows_domestic = await forward_rows(db, SHIPMENT_OBJECT_DOMESTIC, period_value)
        shipment_rows_export = await forward_rows(db, SHIPMENT_OBJECT_EXPORT, period_value)
        shipment_detail_rows = await forward_rows(db, SHIPMENT_DETAIL_OBJECT, period_value)
        batches["shipment_periods"] = {
            "domestic": len(shipment_rows_domestic),
            "export": len(shipment_rows_export),
            "detail": len(shipment_detail_rows),
        }
        _, customer_rows = await latest_batch(db, CUSTOMER_OBJECT, None)
        # 退货/退款同样可能发生在接单之后的月份
        return_rows = await forward_rows(db, RETURN_OBJECT, period_value)
        # 生产订单：接单当月或次月建单，往后看 3 期（批次较大，窗口收紧）
        mo_rows = await forward_rows(db, MO_OBJECT, period_value, max_periods=3)
        batches["mo_rows"] = len(mo_rows)
        # 业务员/客户所属业务员：CRM 人员ID → 姓名
        person_index = await _load_person_index(db)
        # 产品字典：型号ID → 型号名称、系列ID → 系列名称
        _, category_rows = await latest_batch(db, PRODUCT_CATEGORY_OBJECT, None)
        _, model_rows = await latest_batch(db, PRODUCT_MODEL_OBJECT, None)
        category_names = {
            int(row["id"]): str(row.get("name") or "") for row in category_rows if row.get("id") is not None
        }
        model_names = {
            int(row["id"]): str(row.get("model") or "") for row in model_rows if row.get("id") is not None
        }
        batches["product_dict"] = {"series": len(category_names), "model": len(model_names)}
        # 基础分类字典：订单的 source（店铺）与 source_platform（平台）都是它的 id
        _, base_rows = await latest_batch(db, BASE_CATEGORY_OBJECT, None)
        base_names = {
            int(row["id"]): str(row.get("name") or "") for row in base_rows if row.get("id") is not None
        }
        batches["base_dict"] = len(base_names)

        # 客户主数据：以客户列表接口为唯一权威来源（订单上的 wangwang 是旺旺号，不是客户名）
        customer_map = {
            int(row["id"]): {
                "name": row.get("name"),
                "number": row.get("number"),
                "principal_id": row.get("principal_id"),
            }
            for row in customer_rows
            if row.get("id")
        }
        return_by_order: dict[str, float] = {}
        for row in return_rows:
            number = str(row.get("number") or "").strip()
            amount = to_number(row.get("account"))
            if number and amount is not None:
                return_by_order[number] = return_by_order.get(number, 0.0) + amount
        shipments_by_order: dict[str, float] = {}
        for row in [*shipment_rows_domestic, *shipment_rows_export]:
            number = str(row.get("order_number") or "").strip()
            qty = to_number(row.get("send_qty"))
            if number and qty:
                shipments_by_order[number] = shipments_by_order.get(number, 0.0) + qty
        # 发货明细（发货时间口径）：key = CRM 订单ID，一张订单多张发货单要相加
        ship_qty_by_order_id: dict[int, float] = {}
        for row in shipment_detail_rows:
            try:
                order_id = int(row.get("order_id"))
            except (TypeError, ValueError):
                continue
            qty = to_number(row.get("send_qty"))
            if qty:
                ship_qty_by_order_id[order_id] = ship_qty_by_order_id.get(order_id, 0.0) + qty
        mo_by_order: dict[str, list[dict]] = {}
        for row in mo_rows:
            key = base_order_number(row.get("FSaleOrderNo"))
            if key:
                mo_by_order.setdefault(key, []).append(row)

        calc_version = await next_calc_version(db, period_value)
        order_count = 0
        mo_linked = 0
        cost_missing = 0
        records: list[OrderFullChainModel] = []

        seen_orders: set[str] = set()
        for trade_type, rows in ((TRADE_DOMESTIC, order_rows_domestic), (TRADE_EXPORT, order_rows_export)):
            for row in rows:
                number = str(row.get("number") or "").strip()
                # 同一订单号可能同时出现在内贸/外贸批次（或历史多批），只保留第一条
                if number and number in seen_orders:
                    continue
                if number:
                    seen_orders.add(number)
                record, quality = build_record(
                    row,
                    trade_type,
                    period_value,
                    calc_version,
                    customer_map,
                    person_index,
                    shipments_by_order,
                    ship_qty_by_order_id,
                    return_by_order,
                    mo_by_order,
                    model_names,
                    category_names,
                    base_names,
                )
                if record is None:
                    continue
                order_count += 1
                if "mo_unlinked" not in quality:
                    mo_linked += 1
                if "cost_missing" in quality:
                    cost_missing += 1
                records.append(record)

        db.add_all(records)
        await db.flush()
        await prune_old_versions(db, period_value, keep=prune_versions)

        run.status = "success"
        run.calc_version = calc_version
        run.order_count = order_count
        run.mo_linked_count = mo_linked
        run.cost_missing_count = cost_missing
        run.source_batches = batches
        run.finished_at = datetime.now(UTC)
        await db.flush()
        logger.info(
            "订单全链路构建完成 period=%s version=%s orders=%s mo_linked=%s cost_missing=%s",
            period_value,
            calc_version,
            order_count,
            mo_linked,
            cost_missing,
        )
        return {
            "period_value": period_value,
            "calc_version": calc_version,
            "order_count": order_count,
            "mo_linked_count": mo_linked,
            "cost_missing_count": cost_missing,
            "source_batches": batches,
        }
    except Exception as exc:  # noqa: BLE001 - 构建失败要把原因写进批次表
        run.status = "failed"
        run.error = str(exc)[:4000]
        run.finished_at = datetime.now(UTC)
        await db.flush()
        logger.exception("订单全链路构建失败 period=%s", period_value)
        raise


def build_record(
    row: dict,
    trade_type: str,
    period_value: str,
    calc_version: int,
    customer_map: dict[int, dict],
    person_index: dict[str, dict],
    shipments_by_order: dict[str, float],
    ship_qty_by_order_id: dict[int, float],
    return_by_order: dict[str, float],
    mo_by_order: dict[str, list[dict]],
    model_names: dict[int, str],
    category_names: dict[int, str],
    base_names: dict[int, str],
) -> tuple[OrderFullChainModel | None, list[str]]:
    """单行 CRM 订单 → 宽表记录。返回 (记录, 质量标记列表)。"""
    number = str(row.get("number") or "").strip()
    if not number:
        return None, []

    quality: list[str] = []
    extra: dict[str, Any] = {}
    for field_code, keys in SOURCE_KEYS.items():
        value = pick(row, keys)
        if value is not None:
            extra[field_code] = value

    # SKU（型号）与产品线（系列）：CRM 给的是编码，宽表存**名称**，编码另存 *_id 字段
    sku_id = to_number(extra.get("sku"))
    extra["sku_id"] = int(sku_id) if sku_id is not None else None
    extra["sku"] = model_names.get(int(sku_id)) if sku_id is not None else None
    series_id = to_number(extra.get("product_series"))
    extra["product_series_id"] = int(series_id) if series_id is not None else None
    extra["product_series"] = category_names.get(int(series_id)) if series_id is not None else None
    # 订单类型：宽表 extra["order_type"] 存名称（批量/打样/零售，覆盖物理列里的编码），
    # 物理列 order_type 仍是 1/2/3 —— 供 /order/page 与开放接口按编码过滤
    order_type_code = str(pick(row, SOURCE_KEYS["order_type"]) or "").strip()
    extra["order_type_code"] = order_type_code or None
    extra["order_type"] = ORDER_TYPE_NAMES.get(order_type_code)
    # 新老客户：同样存名称，编码另存 is_new_code
    is_new_code = str(pick(row, SOURCE_KEYS["is_new"]) or "").strip()
    extra["is_new_code"] = is_new_code or None
    extra["is_new"] = IS_NEW_NAMES.get(is_new_code)
    # 店铺（source）与平台（source_platform）：编码来自基础分类字典，宽表存名称，编码另存 *_id
    platform_id = to_number(extra.get("platform"))
    extra["platform_id"] = int(platform_id) if platform_id is not None else None
    extra["platform"] = base_names.get(int(platform_id)) if platform_id is not None else None
    shop_id = to_number(extra.get("shop"))
    extra["shop_id"] = int(shop_id) if shop_id is not None else None
    extra["shop"] = base_names.get(int(shop_id)) if shop_id is not None else None

    qty = to_number(pick(row, SOURCE_KEYS["qty"]))
    intake = to_number(pick(row, INTAKE_KEYS_DOMESTIC if trade_type == TRADE_DOMESTIC else INTAKE_KEYS_EXPORT))

    material_cost = to_number(pick(row, MATERIAL_COST_KEYS))
    process_cost = to_number(pick(row, PROCESS_COST_KEYS))
    has_cost = material_cost is not None or process_cost is not None
    total_cost = (material_cost or 0.0) + (process_cost or 0.0) if has_cost else None
    unit_cost = None
    material_cost_unit = None
    if has_cost and qty:
        total_cost = money(total_cost)
        unit_cost = money(total_cost / qty)
        material_cost_unit = money((material_cost or 0.0) / qty)
    extra["unit_cost"] = unit_cost
    extra["material_cost_unit"] = material_cost_unit
    extra["total_cost"] = total_cost
    extra["cost_source"] = "order" if has_cost else "none"
    if not has_cost:
        quality.append("cost_missing")

    order_date = to_date(pick(row, ["createtime"]))
    push_date = to_datetime(pick(row, DATETIME_KEYS["push_date"]))
    finish_date = to_datetime(pick(row, DATETIME_KEYS["finish_date"]))
    ship_date = to_datetime(pick(row, DATETIME_KEYS["ship_date"]))
    promised_date = to_date(pick(row, SOURCE_KEYS["promised_date"]))
    extra["promised_date"] = promised_date

    mo_rows = mo_by_order.get(number, [])
    if mo_rows:
        mo_numbers = sorted({str(item.get("FBillNo")) for item in mo_rows if item.get("FBillNo")})
        extra["mo_numbers"] = ",".join(mo_numbers)
        # 业务口径：下推单号就是生产工单号（金蝶 PRD_MO 单据编号）
        extra["push_no"] = extra["mo_numbers"]
        inbound_qty, inbound_approx = pick_inbound_qty(mo_rows)
        if inbound_approx:
            quality.append("inbound_qty_approx")
        extra["inbound_qty"] = money(inbound_qty)
        mo_start = min((to_datetime(item.get("FStartDate")) for item in mo_rows if item.get("FStartDate")), default=None)
        mo_finish = max((to_datetime(item.get("FFinishDate")) for item in mo_rows if item.get("FFinishDate")), default=None)
        extra["production_cycle"] = days_between(mo_start, mo_finish)
        if finish_date is None:
            finish_date = mo_finish
        extra["actual_date"] = (ship_date or mo_finish).date() if (ship_date or mo_finish) else None
        if extra.get("promised_date") is None:
            extra["promised_date"] = to_date(next((item.get("F_NTHM_Remarks_jhrq") for item in mo_rows if item.get("F_NTHM_Remarks_jhrq")), None))
    else:
        quality.append("mo_unlinked")
        extra["push_no"] = None
        extra["production_cycle"] = None
        extra["actual_date"] = ship_date.date() if ship_date else None

    send_qty = shipments_by_order.get(number)
    ship_untaxed = money(send_qty * (intake / qty)) if (send_qty and qty and intake) else None
    # 出货数量：优先取「发货明细」（发货时间口径，按 CRM 订单ID 关联），
    # 未命中时回退「发货明细 orderShipments」（审核日期口径，按订单号关联）
    order_id = to_number(row.get("id"))
    order_id = int(order_id) if order_id else None
    ship_qty_detail = ship_qty_by_order_id.get(order_id) if order_id else None
    if ship_qty_detail:
        ship_qty = money(ship_qty_detail)
        ship_qty_source = "shipment_detail"
    elif send_qty:
        ship_qty = money(send_qty)
        ship_qty_source = "order_shipments"
    else:
        ship_qty = None
        ship_qty_source = "none"
    extra["order_id"] = order_id
    extra["ship_qty"] = ship_qty
    extra["ship_qty_source"] = ship_qty_source
    return_refund = return_by_order.get(number)
    design_service_income = to_number(pick(row, ["design_remove_taxes_freight", "design_cost"]))
    if ship_untaxed is None and send_qty is None:
        net_shipment = None
    else:
        net_shipment = money((ship_untaxed or 0.0) + (design_service_income or 0.0) - (return_refund or 0.0))
    extra["ship_untaxed"] = ship_untaxed
    extra["design_service_income"] = money(design_service_income) if design_service_income is not None else None
    extra["return_refund"] = money(return_refund)
    extra["net_shipment"] = net_shipment

    gross_profit = None
    gross_profit_rate = None
    # 业务口径：订单毛利 = 净出货 − 标准单位成本 × 入库数量
    # （不是「净出货 − 整单成本」；成本按实际入库数量结转，未入库则扣减为 0）
    cost_basis = None
    inbound_for_cost = extra.get("inbound_qty")
    if unit_cost is not None and inbound_for_cost is not None:
        cost_basis = money(unit_cost * float(inbound_for_cost))
    extra["cost_basis"] = cost_basis
    # 入库未税 = 标准单位成本 × 入库数量（与毛利扣减口径一致，即已入库部分的成本）
    extra["inbound_untaxed"] = cost_basis
    if net_shipment is not None and cost_basis is not None:
        gross_profit = money(net_shipment - cost_basis)
        gross_profit_rate = round(gross_profit / net_shipment, RATE_SCALE) if net_shipment else None
    extra["gross_profit"] = gross_profit
    extra["gross_profit_rate"] = gross_profit_rate
    # 业务口径：订单边际贡献 = 净出货 − 标准材料成本 × 入库数量
    # （与毛利同口径，只扣材料；加工费不计入变动成本）
    material_basis = None
    if material_cost_unit is not None and inbound_for_cost is not None:
        material_basis = money(material_cost_unit * float(inbound_for_cost))
    extra["material_cost_basis"] = material_basis
    contribution_margin = None
    contribution_margin_rate = None
    if net_shipment is not None and material_basis is not None:
        contribution_margin = money(net_shipment - material_basis)
        contribution_margin_rate = (
            round(contribution_margin / net_shipment, RATE_SCALE) if net_shipment else None
        )
    extra["contribution_margin"] = contribution_margin
    extra["contribution_margin_rate"] = contribution_margin_rate
    # 应收余额/逾期天数是客户维度，未与订单打通
    extra["ar_balance"] = None
    extra["overdue_days"] = None
    extra["payment_amount"] = None

    extra["push_period"] = days_between(order_date and datetime(order_date.year, order_date.month, order_date.day), push_date)
    extra["ship_cycle"] = days_between(finish_date, ship_date)
    extra["full_cycle"] = days_between(
        order_date and datetime(order_date.year, order_date.month, order_date.day), ship_date
    )
    customer_id = to_number(pick(row, SOURCE_KEYS["customer_id"]))
    if customer_id is not None:
        customer = customer_map.get(int(customer_id)) or {}
        # 客户列表是权威来源：查到就用它覆盖订单上的值（订单上的 wangwang 只是聊天账号）
        extra["customer_name"] = customer.get("name") or extra.get("customer_name")
        extra["customer_number"] = customer.get("number")
        principal = customer.get("principal_id")
        extra["customer_principal"] = str(principal) if principal is not None else None
        extra["customer_principal_name"] = (
            (person_index.get(str(principal)) or {}).get("person_name") if principal is not None else None
        )
    else:
        extra["customer_number"] = None
        extra["customer_principal"] = None
        extra["customer_principal_name"] = None

    quality_flag = "ok" if not quality else ",".join(sorted(set(quality)))
    # 是否准时：实际交期 ≤ 预定交期 → 准时，否则超时；两者缺一则为空
    actual_date = to_date(extra.get("actual_date"))
    promised_date = to_date(extra.get("promised_date"))
    if actual_date is not None and promised_date is not None:
        extra["on_time"] = "准时" if actual_date <= promised_date else "超时"
    else:
        extra["on_time"] = None
    # 业务员姓名：CRM 下单人 create_id → 标准人员姓名
    salesman_raw = pick(row, SOURCE_KEYS["salesman_code"])
    extra["salesman_name"] = (
        (person_index.get(str(salesman_raw)) or {}).get("person_name") if salesman_raw is not None else None
    ) or extra.get("salesman_name")
    extra["data_quality_flag"] = quality_flag
    extra["schema_version"] = SCHEMA_VERSION
    extra = jsonable(extra)

    record = OrderFullChainModel(
        order_number=number,
        period_value=period_value,
        calc_version=calc_version,
        order_id=order_id,
        trade_type=trade_type,
        order_type=str(pick(row, SOURCE_KEYS["order_type"])) if pick(row, SOURCE_KEYS["order_type"]) is not None else None,
        customer_id=int(customer_id) if customer_id is not None else None,
        salesman_code=str(pick(row, SOURCE_KEYS["salesman_code"])) if pick(row, SOURCE_KEYS["salesman_code"]) is not None else None,
        order_date=order_date,
        push_date=push_date,
        finish_date=finish_date,
        ship_date=ship_date,
        qty=Decimal(str(qty)) if qty is not None else None,
        intake_untaxed=Decimal(str(money(intake))) if intake is not None else None,
        ship_untaxed=Decimal(str(ship_untaxed)) if ship_untaxed is not None else None,
        ship_qty=Decimal(str(ship_qty)) if ship_qty is not None else None,
        net_shipment=Decimal(str(net_shipment)) if net_shipment is not None else None,
        extra=extra,
        data_quality_flag=quality_flag,
    )
    return record, quality


SCHEMA_VERSION = "2026-10-13"


async def prune_old_versions(db: AsyncSession, period_value: str, keep: int = 3) -> int:
    """每个订单只保留最近 ``keep`` 个版本，更早的物理删除。"""
    versions = (
        await db.execute(
            select(OrderFullChainModel.calc_version)
            .where(OrderFullChainModel.period_value == period_value)
            .distinct()
            .order_by(OrderFullChainModel.calc_version.desc())
        )
    ).scalars().all()
    if len(versions) <= keep:
        return 0
    stale = list(versions[keep:])
    await db.execute(
        delete(OrderFullChainModel).where(
            OrderFullChainModel.period_value == period_value,
            OrderFullChainModel.calc_version.in_(stale),
        )
    )
    return len(stale)
