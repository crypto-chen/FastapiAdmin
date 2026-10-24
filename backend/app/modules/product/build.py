"""产品线分析构建：把「订单全链路宽表」按 产品线大类 × SKU 聚合，生成 PRD-xx 指标。

数据流（详见 ``docs/营销中心产品线分析报表方案.md``）::

    dwd_order_full_chain（期间最新版本，一行一单）
      ├─ 型号字典 /hs/product/getProductModel（最新批次）→ SKU=model；型号 id → category_id
      ├─ 系列字典 /hs/product/getProductCategory（最新批次）→ category_id 上卷产品线大类
      └─ 公司级比例：营销结算收入 10%（PRD-27）、总部分摊 2.00%（PRD-33）
      ↓  按 (产品线大类, SKU) 聚合
    dwd_product_line_analysis（期间 × 产品线 × SKU × calc_version）

P0 只落「现用可出」的 26 项；出货数量（PRD-11/12、X03）与成本四项拆分（PRD-08/09/10）
仍为缺项，构建时留空并写进 ``warnings``。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel
from app.modules.metadata.sync import extract_payload_rows
from app.modules.order.model import OrderFullChainModel

from .fields import (
    PRODUCT_CATEGORY_OBJECT,
    PRODUCT_MODEL_OBJECT,
)
from .model import CostBillWorkOrderModel, ProductLineAnalysisModel, ProductLineBuildRunModel

logger = logging.getLogger(__name__)

# 系列字典根节点（产品分类）与容器节点（其子类才是真正的产品线大类）
PRODUCT_CATEGORY_ROOT_ID = 1
CONTAINER_PRODUCT_NAMES = {"未知", "其它", "新产品"}
COST_BILL_OBJECT = "CB_CostCalBill"  # 金蝶成本计算单（按销售订单号关联，取本期完工单位成本）

ORDER_TYPE_NAMES = {"1": "批量", "2": "打样", "3": "零售", "4": "备货"}
SETTLEMENT_RATE = 0.10  # PRD-27 营销结算收入 10%
HQ_ALLOCATION_RATE = 0.02  # PRD-33 总部分摊 2.00%（底稿 27×2%）
VARIABLE_EXPENSE_RATE = 0.28  # PRD-29 变动费用分摊 28%（2026-10-17 业务确认：按净额比例分摊列示）
FIXED_EXPENSE_RATE = 0.06  # PRD-32 固定费用分摊 6%（同上）
STAGNANT_DAYS = 90  # PRD-39 呆滞库存：入库后超过该天数仍未出货
TURNOVER_DAYS = 30  # PRD-40 库存周转天数按 30 天折算

PENDING_NOTES: list[str] = [
    "标准成本组取 CRM 销售订单：PRD-11/12/16/17 与平均产品单价已出；PRD-13/14/15 阻塞于订单行缺人工与制造费用拆分字段",
    "费用与收益（PRD-29~35）按 2026-10-17 确认的口径以净额固定比例分摊列示：变动 28%、固定 6%、总部 2%",
    "毛利（PRD-41/42）按底稿口径 = 对外出货净额 − 标准成本小计（PRD-16）；PRD-43/44 仍缺标准制造费用变动",
    "实际成本组（PRD-06/08/09/10）取 ERP 成本计算单：参数已打通，待建来源对象与同步任务（拆分列还需另调显示方式）",
    "PRD-05 BOM版本取 ERP 成本计算单 FBOMNUMBERFIELD_FNUMBER：待建同步任务",
]

# 多值拼接字段（同一产品线当月多个取值 → 按金额降序 `/` 拼接）
CONCAT_KEYS = ("order_type", "salesman", "platform", "shop")


def to_number(value: Any) -> float:
    if value is None or value == "" or value == "-":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def money(value: float) -> float:
    return round(float(value or 0), 4)


def percent(numerator: float, denominator: float) -> float | None:
    """比率统一按百分数存储（如 37.8089 表示 37.8089%），分母为 0 返回 None。"""
    if not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100, 4)


def period_end_date(period_value: str) -> date:
    """``YYYY-MM`` → 期间末日（呆滞库龄的截止日）。"""
    year, month = (int(part) for part in period_value.split("-")[:2])
    leap = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    last_day = [31, leap, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, last_day)


def previous_period_value(period_value: str) -> str:
    year, month = (int(part) for part in period_value.split("-")[:2])
    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year}-{month:02d}"


def _concat(counter: dict[str, float]) -> str:
    """多值拼接：按金额降序，金额相同按名称升序，``/`` 分隔，空值不参与。"""
    items = [(key, value) for key, value in counter.items() if key]
    items.sort(key=lambda item: (-item[1], item[0]))
    return "/".join(key for key, _value in items)


async def _latest_run_rows(db: AsyncSession, object_code: str) -> list[dict]:
    """取某来源对象最近一次成功批次的明细行。"""
    run_id = (
        await db.execute(
            select(MetaSyncRunModel.id)
            .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
            .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
            .where(SourceObjectModel.code == object_code, MetaSyncRunModel.status == "success")
            .order_by(MetaSyncRunModel.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if run_id is None:
        return []
    rows = (
        await db.execute(select(MetaSyncRunModel.rows_json).where(MetaSyncRunModel.id == run_id))
    ).scalars().first()
    return list(extract_payload_rows(rows) or [])


def category_line_map(rows: list[dict]) -> dict[int, str]:
    """系列字典：``category_id`` → 产品线大类（沿父链上卷，容器节点再下沉一层）。

    与 ``app/modules/customer/build.py::product_line_map`` 同一套上卷规则。
    """
    parent: dict[int, int] = {}
    name: dict[int, str] = {}
    for row in rows:
        try:
            node = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        try:
            pid = int(row.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        parent[node] = pid
        name[node] = str(row.get("name") or "").strip()

    def resolve(node: int) -> str:
        path: list[int] = []
        current, guard = node, 0
        while guard < 20:
            path.append(current)
            pid = parent.get(current)
            if pid in (None, 0, PRODUCT_CATEGORY_ROOT_ID):
                break
            if pid not in parent:
                break
            current, guard = pid, guard + 1
        path.reverse()
        if not path:
            return ""
        top = path[0]
        if name.get(top) in CONTAINER_PRODUCT_NAMES and len(path) > 1:
            return name.get(path[1], "")
        return name.get(top, "")

    return {node: resolve(node) for node in parent if node != PRODUCT_CATEGORY_ROOT_ID}


def model_index(rows: list[dict]) -> dict[int, dict[str, Any]]:
    """型号字典：型号 id → {model, category_id}。"""
    index: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            node = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        try:
            category_id = int(row.get("category_id")) if row.get("category_id") not in (None, "") else None
        except (TypeError, ValueError):
            category_id = None
        index[node] = {"model": str(row.get("model") or "").strip(), "category_id": category_id}
    return index


async def _latest_order_rows(db: AsyncSession, period_value: str) -> tuple[list[OrderFullChainModel], int]:
    version = (
        await db.execute(
            select(func.max(OrderFullChainModel.calc_version)).where(
                OrderFullChainModel.period_value == period_value
            )
        )
    ).scalar()
    if version is None:
        return [], 0
    rows = (
        await db.execute(
            select(OrderFullChainModel)
            .where(
                OrderFullChainModel.period_value == period_value,
                OrderFullChainModel.calc_version == version,
            )
            .order_by(OrderFullChainModel.order_number)
        )
    ).scalars().all()
    return list(rows), int(version)


async def _load_previous_inventory(
    db: AsyncSession, period_value: str
) -> tuple[dict[tuple[str, str], float], dict[str, float], float]:
    """取上一期最新版本的产品线库存（PRD-36），用于 PRD-40 的平均库存。

    返回：明细映射 (产品线, SKU)→库存、产品线小计映射、全表合计。
    """
    previous = previous_period_value(period_value)
    version = (
        await db.execute(
            select(func.max(ProductLineAnalysisModel.calc_version)).where(
                ProductLineAnalysisModel.period_value == previous
            )
        )
    ).scalar()
    if version is None:
        return {}, {}, 0.0
    rows = (
        await db.execute(
            select(ProductLineAnalysisModel).where(
                ProductLineAnalysisModel.period_value == previous,
                ProductLineAnalysisModel.calc_version == version,
                ProductLineAnalysisModel.is_aggregate == 0,
            )
        )
    ).scalars().all()
    detail: dict[tuple[str, str], float] = {}
    line: dict[str, float] = {}
    total = 0.0
    for row in rows:
        value = to_number((row.extra or {}).get("PRD-36"))
        detail[(row.product_line_code or "", row.sku or "")] = value
        line[row.product_line_code or ""] = line.get(row.product_line_code or "", 0.0) + value
        total += value
    return detail, line, total


async def _load_cost_bill_unit_cost(
    db: AsyncSession, period_value: str, work_order_to_bucket: dict[str, tuple[str, str]]
) -> tuple[dict[tuple[str, str], float], dict[str, Any]]:
    """成本计算单 → 各「产品线×SKU」的本期完工单位成本平均值。

    关联：成本计算单 ``FPRODUCTNO``（工单号，形如 ``MO043786``）↔ 订单全链路 ``extra.push_no``
    （CRM 单号与 ERP 销售订单号是两套编号，没有共同字段，工单号是唯一可靠的公共键）；
    只取本期完工行（``FCompleteQty > 0``），单位成本取 ``FProductUseCost``，按 SKU 做**简单平均**。
    """
    run_id = (
        await db.execute(
            select(MetaSyncRunModel.id)
            .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
            .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
            .where(
                SourceObjectModel.code == COST_BILL_OBJECT,
                MetaSyncRunModel.status == "success",
                MetaSyncRunModel.period_value == period_value,
            )
            .order_by(MetaSyncRunModel.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if run_id is None:
        return {}, {"source": "none", "rows": 0, "completed": 0, "matched": 0, "skus": 0}

    payload = (
        await db.execute(select(MetaSyncRunModel.rows_json).where(MetaSyncRunModel.id == run_id))
    ).scalars().first()
    rows = payload.get("Rows") if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []

    source_object = (
        await db.execute(select(SourceObjectModel).where(SourceObjectModel.code == COST_BILL_OBJECT))
    ).scalars().first()
    field_keys = ((source_object.request_template or {}) if source_object else {}).get("FieldKeys") or ""
    fields = [item.strip() for item in str(field_keys).split(",") if item.strip()]
    index = {name: i for i, name in enumerate(fields)}

    def cell(row: list, name: str) -> Any:
        i = index.get(name)
        if i is None or not isinstance(row, list) or i >= len(row):
            return None
        return row[i]

    totals: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}
    bom_counter: dict[tuple[str, str], dict[str, int]] = {}
    completed = 0
    matched = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        # BOM 版本：不要求完工，只要有工单归属就统计（取出现次数最多的版本）
        work_order = str(cell(row, "FPRODUCTNO") or "").strip()
        if not work_order:
            bill_no = str(cell(row, "FOrderBillNo") or "").strip()
            work_order = bill_no.rsplit("-", 1)[0] if "-" in bill_no else bill_no
        bucket = work_order_to_bucket.get(work_order)
        if bucket is not None:
            bom = str(cell(row, "FBOMNUMBERFIELD_FNUMBER") or "").strip().strip('"')
            if bom:
                counter = bom_counter.setdefault(bucket, {})
                counter[bom] = counter.get(bom, 0) + 1
        if to_number(cell(row, "FCompleteQty")) <= 0:
            continue
        unit_cost = to_number(cell(row, "FProductUseCost"))
        if unit_cost <= 0:
            continue
        completed += 1
        if bucket is None:
            continue
        matched += 1
        totals[bucket] = totals.get(bucket, 0.0) + unit_cost
        counts[bucket] = counts.get(bucket, 0) + 1

    averages = {key: round(totals[key] / counts[key], 4) for key in totals if counts[key]}
    bom_by_bucket = {
        key: max(counter.items(), key=lambda kv: (kv[1], kv[0]))[0]
        for key, counter in bom_counter.items()
    }
    return averages, {
        "source": "cost_bill",
        "rows": len(rows),
        "completed": completed,
        "matched": matched,
        "skus": len(averages),
        "bom_skus": len(bom_by_bucket),
        "bom": bom_by_bucket,
    }


async def _load_cost_bill_material_unit(
    db: AsyncSession, period_value: str, work_order_to_bucket: dict[str, tuple[str, str]]
) -> dict[tuple[str, str], float]:
    """成本计算单（工单级表）→ 各「产品线×SKU」的实际材料单位成本平均值。

    单位材料成本 = 工单材料成本 ÷ 工单本期完工数量，再按 SKU 简单平均。
    """
    rows = (
        await db.execute(
            select(CostBillWorkOrderModel).where(
                CostBillWorkOrderModel.period_value == period_value,
                CostBillWorkOrderModel.complete_qty > 0,
                CostBillWorkOrderModel.material_cost > 0,
            )
        )
    ).scalars().all()
    totals: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        bucket = work_order_to_bucket.get(str(row.work_order or ""))
        if bucket is None:
            continue
        unit = to_number(row.material_cost) / to_number(row.complete_qty)
        if unit <= 0:
            continue
        totals[bucket] = totals.get(bucket, 0.0) + unit
        counts[bucket] = counts.get(bucket, 0) + 1
    return {key: round(totals[key] / counts[key], 4) for key in totals if counts[key]}


async def _load_cost_bill_overhead_unit(
    db: AsyncSession, period_value: str, work_order_to_bucket: dict[str, tuple[str, str]]
) -> dict[tuple[str, str], float]:
    """成本计算单（工单级表）→ 各「产品线×SKU」的实际制造费用单位成本平均值。

    单位制造费用 = 工单制造费用（非材料、非直接人工的费用项目）÷ 工单完工数量，再按 SKU 简单平均。
    """
    rows = (
        await db.execute(
            select(CostBillWorkOrderModel).where(
                CostBillWorkOrderModel.period_value == period_value,
                CostBillWorkOrderModel.complete_qty > 0,
                CostBillWorkOrderModel.other_cost > 0,
            )
        )
    ).scalars().all()
    totals: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        bucket = work_order_to_bucket.get(str(row.work_order or ""))
        if bucket is None:
            continue
        unit = to_number(row.other_cost) / to_number(row.complete_qty)
        if unit <= 0:
            continue
        totals[bucket] = totals.get(bucket, 0.0) + unit
        counts[bucket] = counts.get(bucket, 0) + 1
    return {key: round(totals[key] / counts[key], 4) for key in totals if counts[key]}


def _empty_bucket(product_line: str, sku: str) -> dict[str, Any]:
    return {
        "product_line_code": product_line or None,
        "product_line_name": product_line or None,
        "sku": sku or None,
        "order_count": 0,
        "ship_qty": 0.0,
        "intake_untaxed": 0.0,
        "ship_untaxed": 0.0,
        "design_income": 0.0,
        "return_refund": 0.0,
        "net_shipment": 0.0,
        "gross_profit": 0.0,
        "contribution_margin": 0.0,
        "material_cost_amount": 0.0,
        "material_cost_qty": 0.0,
        "process_cost_amount": 0.0,
        "process_cost_qty": 0.0,
        "unit_cost_amount": 0.0,
        "unit_cost_qty": 0.0,
        # 库存（成本口径）：接单余额 / 在制 / 完工齐套未出货 / 呆滞（>90 天）
        "inv_order_balance": 0.0,
        "inv_wip": 0.0,
        "inv_finished": 0.0,
        "inv_stagnant": 0.0,
        "order_type_counter": {},
        "order_type_amount": {},
        "order_type_qty": {},
        "salesman_counter": {},
        "platform_counter": {},
        "shop_counter": {},
    }


def _add(store: dict[str, Any], row: OrderFullChainModel, period_end: date) -> None:
    """把一张订单行累加进某个桶。"""
    extra = row.extra or {}
    store["order_count"] += 1
    store["ship_qty"] += to_number(row.ship_qty)
    store["intake_untaxed"] += to_number(row.intake_untaxed)
    store["ship_untaxed"] += to_number(row.ship_untaxed)
    store["design_income"] += to_number(extra.get("design_service_income"))
    store["return_refund"] += to_number(extra.get("return_refund"))
    store["net_shipment"] += to_number(row.net_shipment)
    store["gross_profit"] += to_number(extra.get("gross_profit"))
    store["contribution_margin"] += to_number(extra.get("contribution_margin"))

    unit_material = to_number(extra.get("material_cost_unit"))
    qty = to_number(row.qty)
    if unit_material and qty:
        store["material_cost_amount"] += unit_material * qty
        store["material_cost_qty"] += qty
    # 标准成本取 CRM 销售订单上的标准单位成本（material_cost_total + process_cost ÷ 数量）
    unit_cost = to_number(extra.get("unit_cost"))
    if unit_cost and qty:
        store["unit_cost_amount"] += unit_cost * qty
        store["unit_cost_qty"] += qty
    # 人工成本 = CRM 订单行的 process_cost（加工费）
    unit_process = to_number(extra.get("process_cost_unit"))
    if unit_process and qty:
        store["process_cost_amount"] += unit_process * qty
        store["process_cost_qty"] += qty

    # 库存（成本口径，取 CRM 订单）：未出货数量 × 标准单位成本，按节点分三段
    unsold = qty - to_number(row.ship_qty)
    if unsold > 0 and unit_cost:
        cost = unit_cost * unsold
        if row.push_date is None:
            store["inv_order_balance"] += cost  # 接单余额：已接单未下推
        elif row.finish_date is None:
            store["inv_wip"] += cost  # 在制：已下推未齐套
        else:
            store["inv_finished"] += cost  # 完工齐套未出货
            if row.finish_date.date() <= period_end - timedelta(days=STAGNANT_DAYS):
                store["inv_stagnant"] += cost  # 呆滞：入库超 90 天仍未出库

    amount = to_number(row.intake_untaxed)
    order_type = ORDER_TYPE_NAMES.get(str(extra.get("order_type_code") or "").strip(), "")
    if order_type:
        store["order_type_counter"][order_type] = store["order_type_counter"].get(order_type, 0.0) + amount
        store["order_type_amount"][order_type] = store["order_type_amount"].get(order_type, 0.0) + amount
        store["order_type_qty"][order_type] = store["order_type_qty"].get(order_type, 0.0) + qty

    salesman = str(extra.get("salesman_name") or row.salesman_code or "").strip()
    if salesman:
        store["salesman_counter"][salesman] = store["salesman_counter"].get(salesman, 0.0) + amount
    platform = str(extra.get("platform") or "").strip()
    if platform:
        store["platform_counter"][platform] = store["platform_counter"].get(platform, 0.0) + amount
    shop = str(extra.get("shop") or "").strip()
    if shop:
        store["shop_counter"][shop] = store["shop_counter"].get(shop, 0.0) + amount


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """把明细桶累加进小计/合计桶（不含身份字段）。"""
    for key in (
        "order_count",
        "ship_qty",
        "intake_untaxed",
        "ship_untaxed",
        "design_income",
        "return_refund",
        "net_shipment",
        "gross_profit",
        "contribution_margin",
        "material_cost_amount",
        "material_cost_qty",
        "process_cost_amount",
        "process_cost_qty",
        "unit_cost_amount",
        "unit_cost_qty",
        "inv_order_balance",
        "inv_wip",
        "inv_finished",
        "inv_stagnant",
    ):
        target[key] += source[key]
    for counter_key in ("order_type_counter", "order_type_amount", "order_type_qty", "salesman_counter", "platform_counter", "shop_counter"):
        target_counter = target[counter_key]
        for name, value in source[counter_key].items():
            target_counter[name] = target_counter.get(name, 0.0) + value


def _extra_of(store: dict[str, Any]) -> dict[str, Any]:
    """桶 → PRD-xx 字段区（只写本期能出的 26 项）。"""
    order_count = int(store["order_count"])
    ship_qty = money(store["ship_qty"])
    net_shipment = money(store["net_shipment"])
    settlement_income = money(net_shipment * SETTLEMENT_RATE)  # PRD-27
    # 2026-10-17 业务确认：变动费用分摊 = 净额 × 28%，固定费用分摊 = 净额 × 6%（分摊列示，非实际发生额）
    variable_allocation = money(net_shipment * VARIABLE_EXPENSE_RATE)  # PRD-29
    fixed_allocation = money(net_shipment * FIXED_EXPENSE_RATE)  # PRD-32
    hq_allocation = money(net_shipment * HQ_ALLOCATION_RATE)  # PRD-33
    # 2026-10-17 业务确认：边际贡献 = 对外出货净额 − 变动费用分摊（不是营销结算收入 10% − 变动费用）
    contribution = money(net_shipment - variable_allocation)  # PRD-30
    contribution_rate = percent(contribution, net_shipment)  # PRD-31 = 边际贡献率（分母为净额）
    settlement = money(contribution - fixed_allocation - hq_allocation)  # PRD-34 = 31−33−34
    settlement_rate = percent(settlement, net_shipment)  # PRD-35 = 35÷27
    material_unit = (
        money(store["material_cost_amount"] / store["material_cost_qty"])
        if store["material_cost_qty"]
        else None
    )
    process_unit = (
        money(store["process_cost_amount"] / store["process_cost_qty"])
        if store["process_cost_qty"]
        else None
    )
    standard_unit_cost = (
        money(store["unit_cost_amount"] / store["unit_cost_qty"]) if store["unit_cost_qty"] else None
    )
    # PRD-12 标准材料成本 = 材料单位成本 × 出货数量
    material_cost_total = money(material_unit * ship_qty) if (material_unit and ship_qty) else None
    # PRD-14 标准制造费用 = CRM 订单加工费（process_cost）单位成本 × 出货数量（2026-10-17 业务指定）
    overhead_total = money(process_unit * ship_qty) if (process_unit and ship_qty) else None
    # PRD-16 标准成本小计 = PRD-12 标准材料成本 + PRD-14 标准制造费用；
    # 两项缺一时回退「标准单位成本 × 出货数量」（与 12+14 等价）
    if material_cost_total is not None and overhead_total is not None:
        standard_cost_total = money(material_cost_total + overhead_total)
    elif standard_unit_cost and ship_qty:
        standard_cost_total = money(standard_unit_cost * ship_qty)
    else:
        standard_cost_total = None
    # 底稿口径（2026-10-17 业务确认不接受替代口径）：毛利 = 对外出货净额 − 标准成本小计
    gross_profit = money(net_shipment - standard_cost_total) if standard_cost_total is not None else None
    gross_profit_rate = percent(gross_profit, net_shipment) if gross_profit is not None else None
    # PRD-43 标准成本边际贡献 = PRD-26 − PRD-12 − PRD-14；PRD-44 = PRD-43 ÷ PRD-26
    standard_contribution = (
        money(net_shipment - material_cost_total - overhead_total)
        if (material_cost_total is not None and overhead_total is not None)
        else None
    )
    standard_contribution_rate = (
        percent(standard_contribution, net_shipment) if standard_contribution is not None else None
    )
    # 库存（成本口径）：PRD-36 = 接单余额 + 在制 + 完工齐套未出货；37/38 为两段明细，39 为 >90 天呆滞
    inventory = money(store["inv_order_balance"] + store["inv_wip"] + store["inv_finished"])
    types = store["order_type_amount"]
    qtys = store["order_type_qty"]
    type_counters = store["order_type_counter"]

    def avg(prefix: str) -> float | None:
        qty = qtys.get(prefix, 0.0)
        return money(types.get(prefix, 0.0) / qty) if qty else None

    return {
        "PRD-00": None,  # 由 period_value 承载，这里留空避免重复
        "PRD-01": store["product_line_code"],
        "PRD-02": store["sku"],
        "PRD-07": material_unit,
        "PRD-11": ship_qty or None,
        "PRD-12": material_cost_total,
        "PRD-16": standard_cost_total,
        "PRD-17": standard_unit_cost,  # 标准成本取 CRM 销售订单（按数量加权平均）
        "PRD-18": _concat(store["salesman_counter"]),
        "PRD-19": _concat(type_counters),
        "PRD-20": _concat(store["platform_counter"]),
        "PRD-21": _concat(store["shop_counter"]),
        "PRD-22": money(store["intake_untaxed"]),
        "PRD-23": money(store["ship_untaxed"]),
        "PRD-24": money(store["design_income"]),
        "PRD-25": money(store["return_refund"]),
        "PRD-26": net_shipment,
        "PRD-27": settlement_income,
        "PRD-29": variable_allocation,
        "PRD-30": contribution,
        "PRD-31": contribution_rate,
        "PRD-32": fixed_allocation,
        "PRD-33": hq_allocation,
        "PRD-34": settlement,
        "PRD-35": settlement_rate,
        # 库存类统一输出数值（0 表示没有库存，便于小计/合计直接相加）
        "PRD-36": inventory,
        "PRD-37": money(store["inv_wip"]),
        "PRD-38": money(store["inv_finished"]),
        "PRD-39": money(store["inv_stagnant"]),
        "PRD-41": gross_profit,
        "PRD-42": gross_profit_rate,
        "PRD-14": overhead_total,
        "PRD-43": standard_contribution,
        "PRD-44": standard_contribution_rate,
        "PRD-X01": order_count,
        "PRD-X02": money(settlement_income / order_count) if order_count else None,
        "PRD-X03": money(net_shipment / ship_qty) if ship_qty else None,
        "PRD-X04": money(types.get("打样", 0.0)),
        "PRD-X05": qtys.get("打样") or None,
        "PRD-X06": avg("打样"),
        "PRD-X07": money(types.get("批量", 0.0)),
        "PRD-X08": qtys.get("批量") or None,
        "PRD-X09": avg("批量"),
        "PRD-X10": money(types.get("零售", 0.0)),
        "PRD-X11": qtys.get("零售") or None,
        "PRD-X12": avg("零售"),
        # 缺项：留空，口径见 warnings
        "PRD-15": None,
    }


async def build_period(db: AsyncSession, period_value: str) -> dict[str, Any]:
    """构建某期间的产品线分析宽表，返回构建结果。"""
    started = datetime.now(UTC)
    order_rows, order_version = await _latest_order_rows(db, period_value)
    model_rows = await _latest_run_rows(db, PRODUCT_MODEL_OBJECT)
    category_rows = await _latest_run_rows(db, PRODUCT_CATEGORY_OBJECT)
    models = model_index(model_rows)
    lines = category_line_map(category_rows)
    period_end = period_end_date(period_value)
    prev_inventory, prev_line_inventory, prev_total_inventory = await _load_previous_inventory(
        db, period_value
    )

    version = int(
        (
            await db.execute(
                select(func.max(ProductLineAnalysisModel.calc_version)).where(
                    ProductLineAnalysisModel.period_value == period_value
                )
            )
        ).scalar()
        or 0
    ) + 1

    run = ProductLineBuildRunModel(
        period_value=period_value,
        calc_version=version,
        status="running",
        warnings=list(PENDING_NOTES),
        started_at=started,
    )
    db.add(run)
    await db.flush()

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    work_order_to_bucket: dict[str, tuple[str, str]] = {}
    matched = 0
    unmatched = 0
    for row in order_rows:
        extra = row.extra or {}
        sku = str(extra.get("sku") or "").strip()
        if "," in sku:
            sku = ""
        product_line = ""
        # 主数据源：型号字典 category_id → 系列字典上卷。
        # 零售单可能返回多个型号（逗号分隔），取第一个能命中字典的型号作为主型号。
        model_ids: list[int] = []
        for value in extra.get("sku_ids") or []:
            try:
                model_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        try:
            primary_model_id = int(extra.get("sku_id")) if extra.get("sku_id") not in (None, "") else None
        except (TypeError, ValueError):
            primary_model_id = None
        if primary_model_id is not None and primary_model_id not in model_ids:
            model_ids.insert(0, primary_model_id)
        model_id = next((item for item in model_ids if item in models), None)
        if model_id is not None:
            matched += 1
            category_id = models[model_id].get("category_id")
            if category_id is not None:
                product_line = lines.get(int(category_id), "")
            sku = models[model_id].get("model") or sku
        else:
            unmatched += 1
        # 兜底：型号未命中时用订单行的 product_series_id（多系列逐个尝试）上卷
        if not product_line:
            series_ids: list[int] = []
            for value in extra.get("product_series_ids") or []:
                try:
                    series_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            try:
                primary_series_id = (
                    int(extra.get("product_series_id"))
                    if extra.get("product_series_id") not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                primary_series_id = None
            if primary_series_id is not None and primary_series_id not in series_ids:
                series_ids.insert(0, primary_series_id)
            product_line = next((lines.get(item, "") for item in series_ids if lines.get(item)), "")
        if not product_line:
            product_line = "未分类"

        key = (product_line, sku)
        store = buckets.setdefault(key, _empty_bucket(product_line, sku))
        push_no = str(extra.get("push_no") or "").strip()
        if push_no:
            work_order_to_bucket[push_no] = key
        _add(store, row, period_end)

    cost_bill_units, cost_bill_stats = await _load_cost_bill_unit_cost(
        db, period_value, work_order_to_bucket
    )
    bom_by_bucket: dict[tuple[str, str], str] = cost_bill_stats.pop("bom", {})
    material_units = await _load_cost_bill_material_unit(db, period_value, work_order_to_bucket)
    overhead_units = await _load_cost_bill_overhead_unit(db, period_value, work_order_to_bucket)

    # 小计（每个产品线大类）与合计
    line_totals: dict[str, dict[str, Any]] = {}
    grand = _empty_bucket("", "")
    for (product_line, _sku), store in buckets.items():
        _merge(line_totals.setdefault(product_line, _empty_bucket(product_line, "")), store)
        _merge(grand, store)

    def emit(store: dict[str, Any], is_aggregate: int) -> None:
        extra = _extra_of(store)
        if is_aggregate == 2:
            extra["PRD-01"] = "全部产品线"
        # PRD-06 实际单位成本 = 成本计算单「本期完工」单位成本平均值（按 SKU 关联）
        if is_aggregate == 0:
            extra["PRD-06"] = cost_bill_units.get((store["product_line_code"] or "", store["sku"] or ""))
            extra["PRD-05"] = bom_by_bucket.get((store["product_line_code"] or "", store["sku"] or ""))
            # PRD-07 实际材料单位成本 = 工单材料成本 ÷ 工单完工数量（完工数量按单据累加）再按 SKU 平均
            extra["PRD-07"] = material_units.get((store["product_line_code"] or "", store["sku"] or ""))
            extra["PRD-09"] = overhead_units.get((store["product_line_code"] or "", store["sku"] or ""))
        elif cost_bill_units:
            weighted = 0.0
            weight = 0.0
            material_weighted = 0.0
            material_weight = 0.0
            overhead_weighted = 0.0
            overhead_weight = 0.0
            for (bucket_line, bucket_sku), bucket in buckets.items():
                if is_aggregate == 1 and bucket_line != store["product_line_code"]:
                    continue
                value = cost_bill_units.get((bucket_line, bucket_sku))
                qty = to_number(bucket["ship_qty"])
                if value is not None and qty:
                    weighted += value * qty
                    weight += qty
                material_value = material_units.get((bucket_line, bucket_sku))
                if material_value is not None and qty:
                    material_weighted += material_value * qty
                    material_weight += qty
                overhead_value = overhead_units.get((bucket_line, bucket_sku))
                if overhead_value is not None and qty:
                    overhead_weighted += overhead_value * qty
                    overhead_weight += qty
            extra["PRD-06"] = round(weighted / weight, 4) if weight else None
            extra["PRD-07"] = round(material_weighted / material_weight, 4) if material_weight else None
            extra["PRD-09"] = round(overhead_weighted / overhead_weight, 4) if overhead_weight else None
            extra["PRD-05"] = None  # BOM 版本是维度属性，小计/合计行不拼接
        else:
            extra["PRD-06"] = None
            extra["PRD-07"] = None
            extra["PRD-09"] = None
            extra["PRD-05"] = None
        # PRD-40 库存周转天数 = 平均库存（(上期+本期)÷2）÷ 本期销售成本 × 30
        current_inventory = to_number(extra.get("PRD-36"))
        sales_cost = to_number(extra.get("PRD-16"))
        if is_aggregate == 0:
            previous_inventory = prev_inventory.get((store["product_line_code"] or "", store["sku"] or ""), 0.0)
        elif is_aggregate == 1:
            previous_inventory = prev_line_inventory.get(store["product_line_code"] or "", 0.0)
        else:
            previous_inventory = prev_total_inventory
        extra["PRD-40"] = (
            round(((previous_inventory + current_inventory) / 2) / sales_cost * TURNOVER_DAYS, 4)
            if sales_cost
            else None
        )
        db.add(
            ProductLineAnalysisModel(
                period_value=period_value,
                calc_version=version,
                is_aggregate=is_aggregate,
                product_line_code=store["product_line_code"] if is_aggregate != 2 else "全部产品线",
                product_line_name=store["product_line_name"] if is_aggregate != 2 else "全部产品线",
                sku=store["sku"],
                order_count=int(store["order_count"]),
                ship_qty=money(store["ship_qty"]) if store["ship_qty"] else None,
                intake_untaxed=money(store["intake_untaxed"]),
                ship_untaxed=money(store["ship_untaxed"]),
                net_shipment=money(store["net_shipment"]),
                gross_profit=money(store["gross_profit"]),
                contribution_margin=money(store["contribution_margin"]),
                extra=extra,
                data_quality_flag=None if matched else "model_unmatched",
            )
        )

    for (_product_line, _sku), store in sorted(buckets.items()):
        emit(store, 0)
    for _product_line, store in sorted(line_totals.items()):
        emit(store, 1)
    emit(grand, 2)

    run.status = "success"
    run.line_count = len(line_totals)
    run.sku_count = len({sku for _line, sku in buckets if sku})
    run.order_count = len(order_rows)
    run.intake_untaxed_sum = money(grand["intake_untaxed"])
    run.net_shipment_sum = money(grand["net_shipment"])
    run.matched_rows = matched
    run.unmatched_rows = unmatched
    run.finished_at = datetime.now(UTC)
    await db.flush()

    result = {
        "period_value": period_value,
        "calc_version": version,
        "line_count": run.line_count,
        "sku_count": run.sku_count,
        "detail_count": len(buckets),
        "order_count": run.order_count,
        "intake_untaxed_sum": run.intake_untaxed_sum,
        "net_shipment_sum": run.net_shipment_sum,
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "order_source_version": order_version,
        "model_count": len(models),
        "category_count": len(lines),
        "cost_bill": cost_bill_stats,
        "warnings": list(PENDING_NOTES),
    }
    logger.info(
        f"产品线分析构建完成 {period_value} v{version}："
        f"产品线 {run.line_count} 个、SKU {run.sku_count} 个、明细 {len(buckets)} 行、"
        f"订单 {run.order_count} 行（命中型号字典 {matched}、未命中 {unmatched}）"
    )
    return result
