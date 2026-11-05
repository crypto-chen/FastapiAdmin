"""导出 REV-01-a-1 / a-2 / a-3 在指定期间参与计算的订单明细（财务核算用）。

三个指标：
- REV-01-a-1 营销中心批量出货（未税）  CRM /hs/getpiliangchuhuo
- REV-01-a-2 营销中心打样出货（未税）  CRM /hs/getdayangchuhuo
- REV-01-a-3 零售出库未税总金额        聚水潭 /open/orders/out/simple/query

导出内容：
1. 指标汇总：系统指标值、最新源接口汇总、明细合计、差异、计算版本与源批次；
2. REV-01-a-1 / a-2 订单明细：CRM 订单主数据 + 发货明细按订单重建，
   未税金额 = 订单未税单价 × 累计发货数量；
3. REV-01-a-3 订单明细 + 商品明细：直接展开聚水潭销售出库单，
   未税金额 = 含税金额 ÷ (1 + 13%)。

用法（在 backend 目录执行）：
    python scripts/export_rev01_order_detail.py --period 2026-10
    python scripts/export_rev01_order_detail.py --period 2026-10 --output D:/exports/rev01.xlsx

说明：CRM 的 getpiliangchuhuo / getdayangchuhuo 只返回汇总金额，不返回订单行；
脚本按指标定义从 CRM 订单主数据（orderAnalyze）与发货明细
（/hs/shipments/getShipmentsDetail）重建订单行，并用源接口汇总做对账。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.jushuitan.aggregate import (  # noqa: E402
    item_amount,
    item_qty,
    order_amount,
    to_untaxed,
)
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    MetaSyncRunModel,
    SourceObjectModel,
)
from app.modules.metric.model import MetricDefModel, MetricRunModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

EXCEL_CODES = ["REV-01-a-1", "REV-01-a-2", "REV-01-a-3"]
METRIC_BY_EXCEL = {
    "REV-01-a-1": "marketing_batch_shipment_untaxed",
    "REV-01-a-2": "marketing_sample_shipment_untaxed",
    "REV-01-a-3": "retail_outbound_untaxed_amount",
}
ORDER_TYPE_LABEL = {"1": "批量", "2": "打样", "3": "零售"}
TRADE_LABEL = {"domestic": "内贸", "export": "外贸", "retail": "零售"}

ORDER_OBJECTS = {
    "domestic": "/hs/order/orderAnalyze?type=1",
    "export": "/hs/order/orderAnalyze?type=2",
}
SHIPMENT_DETAIL_OBJECT = "/hs/shipments/getShipmentsDetail"
JUSHUITAN_OUTBOUND_OBJECT = "/open/orders/out/simple/query"

TITLE_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FILL = PatternFill("solid", fgColor="4472C4")
HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill("solid", fgColor="D9E2F3")
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
AMOUNT_FMT = "#,##0.0000"


def parse_payload(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def payload_rows(payload: dict) -> list[dict]:
    for key in ("data", "datas", "Rows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def scalar_value(payload: dict, path: str = "data.piliangchuhuo") -> float | None:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def text_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def iso_date(value: Any) -> str:
    # CRM 的 createtime 部分批次返回 Unix 秒（如 1761793255），统一转成可读时间
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.strip().isdigit() and len(value.strip()) in (10, 13)
    ):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return text_value(value)
    return text_value(value)[:19].replace("T", " ")


def source_in_period(value: Any, period: str) -> bool:
    return iso_date(value).startswith(period)


def previous_periods(period: str, count: int) -> list[str]:
    year, month = (int(part) for part in period.split("-"))
    periods: list[str] = []
    for _ in range(count):
        periods.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return list(reversed(periods))


async def latest_run_for_object(db, object_code: str, period: str, before: datetime | None):
    stmt = (
        select(MetaSyncRunModel.id)
        .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
        .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
        .where(
            SourceObjectModel.code == object_code,
            MetaSyncRunModel.status == "success",
            MetaSyncRunModel.period_value == period,
        )
        .order_by(MetaSyncRunModel.id.desc())
        .limit(1)
    )
    if before is not None:
        stmt = stmt.where(MetaSyncRunModel.finished_at <= before)
    run_id = (await db.execute(stmt)).scalars().first()
    return await db.get(MetaSyncRunModel, run_id) if run_id else None


async def latest_run_per_period_for_object(
    db, object_code: str, max_period: str | None = None
) -> list[MetaSyncRunModel]:
    stmt = (
        select(func.max(MetaSyncRunModel.id).label("run_id"))
        .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
        .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
        .where(
            SourceObjectModel.code == object_code,
            MetaSyncRunModel.status == "success",
            MetaSyncRunModel.period_value.is_not(None),
        )
        .group_by(MetaSyncRunModel.period_value)
    )
    if max_period:
        stmt = stmt.where(MetaSyncRunModel.period_value <= max_period)
    # 只取主键，避免把 rows_json 一起参与 GROUP BY 的文件排序（大 JSON 会触发
    # MySQL "Out of sort memory"）。随后逐条按主键取回，40 个期间也很快。
    run_ids = list((await db.execute(stmt)).scalars().all())
    runs: list[MetaSyncRunModel] = []
    for run_id in run_ids:
        run = await db.get(MetaSyncRunModel, run_id)
        if run is not None:
            runs.append(run)
    return runs


async def metric_context(db, excel_code: str, period: str):
    code = METRIC_BY_EXCEL[excel_code]
    metric = (
        await db.execute(select(MetricDefModel).where(MetricDefModel.code == code))
    ).scalars().first()
    if metric is None:
        raise SystemExit(f"指标不存在：{excel_code} / {code}")

    value_row = (
        await db.execute(
            select(MetricValueModel)
            .where(
                MetricValueModel.metric_id == metric.id,
                MetricValueModel.period_value == period,
                MetricValueModel.org_id.is_(None),
                MetricValueModel.dept_code.is_(None),
                MetricValueModel.person_code.is_(None),
            )
            .order_by(MetricValueModel.calc_version.desc(), MetricValueModel.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if value_row is None:
        raise SystemExit(f"指标 {excel_code} 在 {period} 没有计算结果，请先重算")

    run = await db.get(MetricRunModel, value_row.run_id) if value_row.run_id else None
    return metric, value_row, run


async def build_crm_detail(db, metric_code: str, period: str, metric_run) -> tuple[list[dict], float, dict]:
    """按 CRM 订单主数据 + 发货明细重建批量/打样出货订单行。"""
    order_type = "1" if metric_code == "marketing_batch_shipment_untaxed" else "2"

    # 1) 订单主数据：每个期间取最新成功批次，按 CRM 订单 ID 建索引
    orders: dict[int, tuple[dict, str]] = {}
    order_runs: list[str] = []
    for trade, object_code in ORDER_OBJECTS.items():
        runs = await latest_run_per_period_for_object(db, object_code)
        for run in runs:
            order_runs.append(run.batch_id or str(run.id))
            for row in payload_rows(parse_payload(run.rows_json)):
                try:
                    order_id = int(row.get("id"))
                except (TypeError, ValueError):
                    continue
                orders[order_id] = (row, trade)

    # 2) 发货明细：取期间前 3 个月到当期的发货数量，订单累计发货量 = 各月 send_qty 之和
    shipment_periods = previous_periods(period, 4)
    send_qty: dict[int, float] = defaultdict(float)
    target_month_order_ids: set[int] = set()
    shipment_runs: list[str] = []
    for month in shipment_periods:
        run = await latest_run_for_object(db, SHIPMENT_DETAIL_OBJECT, month, None)
        if run is None:
            continue
        shipment_runs.append(run.batch_id or str(run.id))
        for row in payload_rows(parse_payload(run.rows_json)):
            try:
                order_id = int(row.get("order_id"))
            except (TypeError, ValueError):
                continue
            qty = number(row.get("send_qty"))
            if qty:
                send_qty[order_id] += qty
            if month == period:
                target_month_order_ids.add(order_id)

    # 3) 发货明细中命中、但订单主数据缺行的订单：用订单全链路宽表兜底
    missing_ids = sorted(order_id for order_id in target_month_order_ids if order_id not in orders)
    fallback: dict[int, dict] = {}
    if missing_ids:
        placeholders = ",".join(str(int(order_id)) for order_id in missing_ids)
        rows = (
            await db.execute(
                text(
                    f"""
                    SELECT order_number, order_type, qty, intake_untaxed, order_date, ship_date, period_value, extra
                    FROM dwd_order_full_chain
                    WHERE JSON_UNQUOTE(JSON_EXTRACT(extra, '$.order_id')) IN ({placeholders})
                    ORDER BY calc_version DESC
                    """
                )
            )
        ).mappings()
        for row in rows:
            extra = parse_payload(row["extra"])
            try:
                order_id = int(extra.get("order_id"))
            except (TypeError, ValueError):
                continue
            fallback.setdefault(order_id, dict(row))

    # 4) 生成订单行
    detail: list[dict] = []
    total = 0.0
    for order_id, shipped in send_qty.items():
        master = orders.get(order_id)
        if master is not None:
            row, trade = master
            row_order_type = text_value(row.get("order_type"))
            chuhuo_date = iso_date(row.get("chuhuo_date"))
            # CRM 部分批次会把已出货订单的 chuhuo_date 留空；此时以发货明细月份为准。
            # 不补这一步会把“10 月已发货、但订单表出货日期为空”的订单漏掉。
            if not chuhuo_date and order_id in target_month_order_ids:
                chuhuo_date = f"{period}（发货月）"
            qty = number(row.get("qty"))
            intake = (
                number(row.get("receivable")) - number(row.get("taxes"))
                if trade == "domestic"
                else number(row.get("receivable_CNY"))
            )
            order_number = text_value(row.get("number"))
            order_date = iso_date(row.get("createtime"))
            customer = text_value(row.get("customer_name")) or text_value(row.get("customer_name_retail"))
            salesman = text_value(row.get("create_id"))
            source = "CRM 订单主数据 + 发货明细"
        else:
            row = fallback.get(order_id)
            if row is None:
                continue
            row_order_type = text_value(row.get("order_type"))
            chuhuo_date = iso_date(row.get("ship_date")) or f"{period}（发货月）"
            qty = number(row.get("qty"))
            intake = number(row.get("intake_untaxed"))
            order_number = text_value(row.get("order_number"))
            order_date = iso_date(row.get("order_date"))
            extra = parse_payload(row.get("extra"))
            customer = text_value(extra.get("customer_name"))
            salesman = text_value(extra.get("salesman_name"))
            trade = "export" if order_number.endswith("WM") else "domestic"
            source = "订单全链路宽表兜底"

        if row_order_type != order_type or qty <= 0:
            continue
        if not source_in_period(chuhuo_date, period):
            continue
        unit_untaxed = intake / qty
        amount = round(unit_untaxed * shipped, 4)
        total += amount
        detail.append(
            {
                "order_number": order_number,
                "order_id": order_id,
                "order_date": order_date,
                "chuhuo_date": chuhuo_date,
                "trade": TRADE_LABEL.get(trade, trade),
                "order_type": ORDER_TYPE_LABEL.get(row_order_type, row_order_type),
                "qty": round(qty, 4),
                "unit_untaxed": round(unit_untaxed, 4),
                "send_qty": round(shipped, 4),
                "amount": amount,
                "customer": customer,
                "salesman": salesman,
                "source": source,
            }
        )

    detail.sort(key=lambda item: item["order_number"])
    return detail, round(total, 4), {
        "order_runs": len(order_runs),
        "shipment_runs": len(shipment_runs),
        "order_count": len(detail),
        "fallback_count": sum(1 for item in detail if item["source"] == "订单全链路宽表兜底"),
    }


async def build_jushuitan_detail(
    db, period: str, metric_run
) -> tuple[list[dict], list[dict], float, dict]:
    """展开聚水潭销售出库单，返回订单行、商品行与合计未税金额。"""
    before = metric_run.started_at if metric_run else None
    run = await latest_run_for_object(db, JUSHUITAN_OUTBOUND_OBJECT, period, before)
    if run is None:
        raise SystemExit(f"聚水潭销售出库在 {period} 没有成功取数批次")
    rows = payload_rows(parse_payload(run.rows_json))

    orders: list[dict] = []
    items: list[dict] = []
    total = 0.0
    for row in rows:
        amount = order_amount(row, amount_source="items.auto")
        untaxed = to_untaxed(amount, 13.0, True)
        total += untaxed
        items_in_order = row.get("items") if isinstance(row.get("items"), list) else []
        orders.append(
            {
                "o_id": text_value(row.get("o_id")),
                "so_id": text_value(row.get("so_id")),
                "io_date": iso_date(row.get("io_date")),
                "shop_id": text_value(row.get("shop_id")),
                "shop_name": text_value(row.get("shop_name")),
                "status": text_value(row.get("status")),
                "amount": round(amount, 4),
                "untaxed": round(untaxed, 4),
                "item_count": len(items_in_order),
                "item_qty": round(item_qty(row), 4),
            }
        )
        for item in items_in_order:
            if not isinstance(item, dict):
                continue
            item_total = item_amount(item, "items.auto")
            items.append(
                {
                    "o_id": text_value(row.get("o_id")),
                    "so_id": text_value(row.get("so_id")),
                    "io_date": iso_date(row.get("io_date")),
                    "shop_name": text_value(row.get("shop_name")),
                    "i_id": text_value(item.get("i_id")),
                    "sku_id": text_value(item.get("sku_id")),
                    "name": text_value(item.get("name")),
                    "properties": text_value(item.get("properties_value")),
                    "qty": round(number(item.get("qty")), 4),
                    "amount": round(item_total, 4),
                    "untaxed": round(to_untaxed(item_total, 13.0, True), 4),
                }
            )

    orders.sort(key=lambda item: item["io_date"])
    items.sort(key=lambda item: (item["io_date"], item["o_id"], item["i_id"]))
    detail_total = round(total, 4)
    order_rounded_total = round(sum(item["untaxed"] for item in orders), 4)
    item_rounded_total = round(sum(item["untaxed"] for item in items), 4)
    order_tail = round(detail_total - order_rounded_total, 4)
    item_tail = round(detail_total - item_rounded_total, 4)
    if abs(order_tail) > 0.00005:
        orders.append(
            {
                "o_id": "尾差调整",
                "so_id": "",
                "io_date": "",
                "shop_id": "",
                "shop_name": "",
                "status": "",
                "amount": 0,
                "untaxed": order_tail,
                "item_count": 0,
                "item_qty": 0,
            }
        )
    if abs(item_tail) > 0.00005:
        items.append(
            {
                "o_id": "尾差调整",
                "so_id": "",
                "io_date": "",
                "shop_name": "",
                "i_id": "",
                "sku_id": "",
                "name": "四舍五入尾差",
                "properties": "",
                "qty": 0,
                "amount": 0,
                "untaxed": item_tail,
            }
        )
    return orders, items, detail_total, {
        "batch_id": run.batch_id,
        "finished_at": iso_date(run.finished_at),
        "order_count": len(orders) - (1 if abs(order_tail) > 0.00005 else 0),
        "item_count": len(items) - (1 if abs(item_tail) > 0.00005 else 0),
        "order_tail": order_tail,
        "item_tail": item_tail,
    }


def write_title(ws, title: str, columns: list[str]):
    ws.append([title] + [""] * (len(columns) - 1))
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(columns))
    cell = ws.cell(row=1, column=1)
    cell.font = TITLE_FONT
    cell.fill = TITLE_FILL
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.append(columns)
    for col in range(1, len(columns) + 1):
        header = ws.cell(row=2, column=col)
        header.font = HEADER_FONT
        header.fill = HEADER_FILL
        header.border = BORDER
        header.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(columns))}{ws.max_row}"


def write_rows(ws, rows: list[list[Any]], amount_columns: set[int] | None = None):
    amount_columns = amount_columns or set()
    for values in rows:
        ws.append(values)
        row_index = ws.max_row
        for col in range(1, len(values) + 1):
            cell = ws.cell(row=row_index, column=col)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center")
            if col in amount_columns:
                cell.number_format = AMOUNT_FMT


def set_widths(ws, widths: list[int]):
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def build_workbook(
    period: str,
    generated_at: datetime,
    summary_rows: list[dict],
    crm_details: dict[str, list[dict]],
    jst_orders: list[dict],
    jst_items: list[dict],
) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)

    # 说明
    ws = wb.create_sheet("导出说明")
    ws.append(["项目", "内容"])
    ws.merge_cells("A1:B1")
    ws["A1"].font = TITLE_FONT
    ws["A1"].fill = TITLE_FILL
    ws["A1"].alignment = Alignment(horizontal="center")
    notes = [
        ("期间", period),
        ("生成时间", generated_at.strftime("%Y-%m-%d %H:%M:%S")),
        ("用途", "财务核算：指标参与计算的订单/商品明细"),
        ("REV-01-a-1", "营销中心批量出货（未税），CRM /hs/getpiliangchuhuo"),
        ("REV-01-a-2", "营销中心打样出货（未税），CRM /hs/getdayangchuhuo"),
        ("REV-01-a-3", "零售出库未税总金额，聚水潭 /open/orders/out/simple/query"),
        (
            "a-1/a-2 明细口径",
            "CRM 源接口只返回汇总金额；明细按同一口径从订单主数据 + 发货明细重建："
            "未税金额 = 订单未税金额 ÷ 订单数量 × 累计发货数量",
        ),
        (
            "a-3 明细口径",
            "按出库时间归月；含税金额取明细 sale_amount → buyer_paid_amount → seller_income_amount "
            "首个非零值；未税 = 含税 ÷ 1.13",
        ),
        ("对账", "每个指标在「指标汇总」中列示系统值、源接口值、明细合计与差异"),
    ]
    for key, value in notes:
        ws.append([key, value])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=2):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 110

    # 指标汇总
    ws = wb.create_sheet("指标汇总")
    headers = [
        "Excel 编码",
        "指标编码",
        "指标名称",
        "期间",
        "指标值",
        "计算版本",
        "计算时间",
        "源接口/明细合计",
        "差异（明细-指标）",
        "订单数",
        "源批次",
        "说明",
    ]
    write_title(ws, f"REV-01 指标汇总 {period}", headers)
    rows = []
    for item in summary_rows:
        rows.append(
            [
                item["excel_code"],
                item["metric_code"],
                item["metric_name"],
                period,
                item["metric_value"],
                item["calc_version"],
                item["calc_time"],
                item["detail_total"],
                item["diff"],
                item["order_count"],
                item["source_batch"],
                item["note"],
            ]
        )
    write_rows(ws, rows, amount_columns={5, 8, 9})
    for row_index in range(3, ws.max_row + 1):
        if abs(number(ws.cell(row=row_index, column=9).value)) > 0.01:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_index, column=col).fill = WARN_FILL
    set_widths(ws, [14, 36, 30, 10, 18, 10, 20, 18, 18, 8, 24, 50])

    # a-1 / a-2 明细
    headers = [
        "序号",
        "订单号",
        "CRM订单ID",
        "接单日期",
        "出货日期",
        "贸易类型",
        "订单类型",
        "订单数量",
        "未税单价",
        "累计发货数量",
        "未税金额",
        "客户名称",
        "业务员",
        "数据来源",
    ]
    for code in ("REV-01-a-1", "REV-01-a-2"):
        ws = wb.create_sheet(f"{code}明细")
        write_title(ws, f"{code} 订单明细 {period}", headers)
        rows = []
        for index, item in enumerate(crm_details.get(code, []), start=1):
            rows.append(
                [
                    index,
                    item["order_number"],
                    item["order_id"],
                    item["order_date"],
                    item["chuhuo_date"],
                    item["trade"],
                    item["order_type"],
                    item["qty"],
                    item["unit_untaxed"],
                    item["send_qty"],
                    item["amount"],
                    item["customer"],
                    item["salesman"],
                    item["source"],
                ]
            )
        write_rows(ws, rows, amount_columns={9, 11})
        set_widths(ws, [7, 22, 12, 18, 20, 10, 10, 12, 14, 14, 16, 30, 12, 24])

    # a-3 订单明细
    ws = wb.create_sheet("REV-01-a-3订单明细")
    headers = [
        "序号",
        "出库单号",
        "线上单号",
        "出库时间",
        "店铺ID",
        "店铺名称",
        "状态",
        "含税金额",
        "未税金额",
        "商品行数",
        "商品数量",
    ]
    write_title(ws, f"REV-01-a-3 销售出库单明细 {period}", headers)
    rows = []
    for index, item in enumerate(jst_orders, start=1):
        rows.append(
            [
                index,
                item["o_id"],
                item["so_id"],
                item["io_date"],
                item["shop_id"],
                item["shop_name"],
                item["status"],
                item["amount"],
                item["untaxed"],
                item["item_count"],
                item["item_qty"],
            ]
        )
    write_rows(ws, rows, amount_columns={8, 9})
    set_widths(ws, [7, 16, 22, 20, 12, 32, 12, 16, 16, 10, 12])

    # a-3 商品明细
    ws = wb.create_sheet("REV-01-a-3商品明细")
    headers = [
        "序号",
        "出库单号",
        "线上单号",
        "出库时间",
        "店铺名称",
        "商品编码",
        "SKU",
        "商品名称",
        "规格",
        "数量",
        "含税金额",
        "未税金额",
    ]
    write_title(ws, f"REV-01-a-3 商品明细 {period}", headers)
    rows = []
    for index, item in enumerate(jst_items, start=1):
        rows.append(
            [
                index,
                item["o_id"],
                item["so_id"],
                item["io_date"],
                item["shop_name"],
                item["i_id"],
                item["sku_id"],
                item["name"],
                item["properties"],
                item["qty"],
                item["amount"],
                item["untaxed"],
            ]
        )
    write_rows(ws, rows, amount_columns={11, 12})
    set_widths(ws, [7, 16, 22, 20, 32, 18, 18, 42, 24, 10, 16, 16])

    return wb


async def main() -> None:
    parser = argparse.ArgumentParser(description="导出 REV-01-a-1/a-2/a-3 订单明细")
    parser.add_argument("--period", required=True, help="期间 YYYY-MM，如 2026-10")
    parser.add_argument("--output", default=None, help="输出 xlsx 路径")
    parser.add_argument(
        "--max-tail",
        type=float,
        default=1.0,
        help="允许的尾差上限（元）；超过视为明细与指标未匹配，默认 1 元",
    )
    args = parser.parse_args()
    period = args.period.strip()

    async with async_db_session() as db:
        contexts = {}
        for excel_code in EXCEL_CODES:
            contexts[excel_code] = await metric_context(db, excel_code, period)

        # a-1 / a-2
        crm_details: dict[str, list[dict]] = {}
        meta: dict[str, dict] = {}
        for excel_code in ("REV-01-a-1", "REV-01-a-2"):
            metric, value_row, run = contexts[excel_code]
            detail, detail_total, info = await build_crm_detail(db, metric.code, period, run)
            metric_value = round(float(value_row.value or 0), 4)
            tail = round(metric_value - detail_total, 4)
            if abs(tail) > args.max_tail:
                raise SystemExit(
                    f"{excel_code} 明细合计 {detail_total:,.4f} 与指标值 {metric_value:,.4f} "
                    f"相差 {tail:+,.4f}，超过尾差上限 {args.max_tail:,.2f}。"
                    "这不是四舍五入尾差：请先重算该指标，或检查服务器订单/发货批次是否完整。"
                )
            if abs(tail) > 0.00005:
                # 逐单金额按 4 位小数四舍五入后与源接口汇总会有极小尾差；
                # 单列一行尾差调整，保证明细合计与指标值一致。
                detail.append(
                    {
                        "order_number": "尾差调整",
                        "order_id": None,
                        "order_date": "",
                        "chuhuo_date": "",
                        "trade": "",
                        "order_type": "",
                        "qty": 0,
                        "unit_untaxed": 0,
                        "send_qty": 0,
                        "amount": tail,
                        "customer": "",
                        "salesman": "",
                        "source": "四舍五入尾差",
                    }
                )
                detail_total = round(detail_total + tail, 4)
                info["tail_diff"] = tail
            source_run = await latest_run_for_object(
                db,
                "/hs/getpiliangchuhuo" if metric.code == "marketing_batch_shipment_untaxed" else "/hs/getdayangchuhuo",
                period,
                run.started_at if run else None,
            )
            source_total = scalar_value(parse_payload(source_run.rows_json)) if source_run else None
            crm_details[excel_code] = detail
            meta[excel_code] = {
                "source_total": source_total,
                "detail_total": detail_total,
                "info": info,
                "source_batch": source_run.batch_id if source_run else "",
            }

        # a-3
        metric3, value3, run3 = contexts["REV-01-a-3"]
        jst_orders, jst_items, jst_total, jst_info = await build_jushuitan_detail(db, period, run3)

    summary_rows = []
    for excel_code in EXCEL_CODES:
        metric, value_row, run = contexts[excel_code]
        metric_value = round(float(value_row.value or 0), 4)
        if excel_code == "REV-01-a-3":
            detail_total = jst_total
            source_total = jst_total
            order_count = jst_info["order_count"]
            source_batch = jst_info["batch_id"]
            note = (
                f"聚水潭出库单 {order_count} 张、商品 {jst_info['item_count']} 行；"
                f"源批次 {jst_info['finished_at']}"
            )
            if jst_info.get("order_tail"):
                note += f"；含四舍五入尾差 {jst_info['order_tail']:+.4f}"
        else:
            detail_total = meta[excel_code]["detail_total"]
            source_total = meta[excel_code]["source_total"]
            order_count = sum(1 for item in crm_details[excel_code] if item["order_number"] != "尾差调整")
            source_batch = meta[excel_code]["source_batch"]
            note = (
                f"CRM 源接口汇总 {source_total:,.4f}；按订单/发货明细重建 {order_count} 张"
                if source_total is not None
                else f"源接口汇总缺失；按订单/发货明细重建 {order_count} 张"
            )
            if meta[excel_code]["info"].get("tail_diff"):
                note += f"；含四舍五入尾差 {meta[excel_code]['info']['tail_diff']:+.4f}"
        summary_rows.append(
            {
                "excel_code": excel_code,
                "metric_code": metric.code,
                "metric_name": metric.name,
                "metric_value": metric_value,
                "calc_version": value_row.calc_version,
                "calc_time": iso_date(value_row.calc_time),
                "detail_total": round(detail_total, 4),
                "diff": round(detail_total - metric_value, 4),
                "order_count": order_count,
                "source_batch": source_batch,
                "note": note,
            }
        )

    generated_at = datetime.now()
    wb = build_workbook(period, generated_at, summary_rows, crm_details, jst_orders, jst_items)
    output = (
        Path(args.output)
        if args.output
        else PROJECT_ROOT / "exports" / f"REV-01_{period}_订单明细_{generated_at:%Y%m%d_%H%M%S}.xlsx"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)

    print(
        json.dumps(
            {
                "period": period,
                "output": str(output.resolve()),
                "metrics": summary_rows,
                "a3_source": jst_info,
                "a1a2_source": meta,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
