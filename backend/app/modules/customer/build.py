"""客户分析构建：把「订单全链路宽表」按客户聚合，生成 CUS-xx 指标。

数据流（详见 ``docs/营销中心客户分析报表方案.md``）::

    dwd_order_full_chain（期间最新版本，一行一单）
      ├─ 客户主档 /hs/customer/getCusotmerList（最新批次）→ 客户名称/编号/所属业务员
      ├─ 产品字典 /hs/product/getProductCategory（最新批次）→ product_series 上卷产品线大类
      └─ metric_value（REV-01 / CM-01 / CM-04 / PER-02 公司合计）→ 边际贡献与结算收益分摊
      ↓  按 customer_id 聚合（金额、单量、多值拼接属性）
    dwd_customer_analysis（期间 × 客户 × calc_version）

本期（P0）落地订单类字段；账龄（CUS-21~27）、回款（CUS-18~20）、库存（CUS-36~38）
与需要上游补字段的项在 ``warnings`` 里标注，字段留空。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.erp.kingdee.client import KingdeeClient
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel
from app.modules.metadata.sync import extract_payload_rows
from app.modules.metric.engine import _load_person_index
from app.modules.metric.model import MetricDefModel, MetricValueModel
from app.modules.order.model import OrderFullChainModel

from .aging import aggregate_by_customer, fetch_aging_rows
from .model import CustomerAnalysisModel, CustomerBuildRunModel

logger = logging.getLogger(__name__)

CUSTOMER_MASTER_OBJECT = "/hs/customer/getCusotmerList"
PRODUCT_DICT_OBJECT = "/hs/product/getProductCategory"
ORDER_OBJECT_DOMESTIC = "/hs/order/orderAnalyze?type=1"
ORDER_OBJECT_EXPORT = "/hs/order/orderAnalyze?type=2"
PRODUCT_CATEGORY_ROOT_ID = 1
# 容器节点：其子类才是真正的产品线大类（钣金外壳 / CNC外壳 / 面板…）
CONTAINER_PRODUCT_NAMES = {"未知", "其它", "新产品"}

ORDER_TYPE_NAMES = {"1": "批量", "2": "打样", "3": "零售", "4": "备货"}
TRADE_NAMES = {"domestic": "内贸", "export": "外贸"}
# 客户主档 type：1 内贸 2 外贸（地区取法不同：内贸 region 省市县，外贸 country 国家）
MASTER_TYPE_NAMES = {"1": "内贸", "2": "外贸"}
INT_KEYS = {"CUS-36-1"}
PERCENT_CODES = {"CUS-19", "CUS-20", "CUS-23", "CUS-29", "CUS-31", "CUS-33", "CUS-35", "CUS-40", "CUS-41"}

# 公司口径指标（分摊基数，见方案 §4.1）
COMPANY_METRIC_CODES: dict[str, str] = {
    "REV-01": "marketing_external_shipment_net_untaxed",
    "CM-01": "marketing_variable_expense_total",
    "CM-04": "marketing_fixed_expense_total",
    "PER-02": "marketing_per02_total",
}
SETTLEMENT_RATE = 0.10  # CUS-17 营销结算收入 = 对外出货净额 × 10%

# 客户维度的应收类指标（已由指标引擎按「往来单位 = 客户」写入 metric_value.dept_code）
AR_BALANCE_CODE = "marketing_ar_balance"
AR_OVERDUE_CODE = "marketing_ar_overdue"
AR_METRIC_CODES = (AR_BALANCE_CODE, AR_OVERDUE_CODE)

PENDING_NOTES: list[str] = [
    "CUS-06 信用等级 / CUS-07 账期 / CUS-44 创建时间 / CUS-45 客户层级 / CUS-46 行业：待上游补字段或对照表",
    "CUS-18 回款 / CUS-19 回款及时率 / CUS-20 订金回款比例：口径待定，本期挂起",
    "CUS-21~27 应收与账龄 / CUS-36~38 库存：P1 接入（应收账龄分析表）",
]

# 地区取值键（内贸用 region，外贸用 country / continents）
REGION_KEYS = ("region", "country", "continents")

AGING_INI = Path(__file__).resolve().parents[3] / "env" / "kindee_conf.ini"


def period_end_date(period_value: str) -> date:
    """``YYYY-MM`` → 期间末日（账龄截止日）。"""
    year, month = (int(part) for part in period_value.split("-")[:2])
    leap = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    last_day = [31, leap, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, last_day)


async def _load_aging_rows(period_value: str) -> dict[str, dict[str, Any]]:
    """取客户 × 账龄分档（CUS-24~27）；金蝶不可用时返回空、不阻断构建。"""
    # 与指标引擎一致：账龄截止日 = 期末日；当期未到期末取今天（避免用未来日期取数）
    as_of = min(period_end_date(period_value), datetime.now().date())
    try:
        client = KingdeeClient.from_ini(AGING_INI)
        rows = await fetch_aging_rows(client, as_of.isoformat(), "")
        data, totals = aggregate_by_customer(rows, as_of)
        logger.info(
            f"账龄取数 {period_value} @{as_of}：明细 {len(rows)} 行、客户 {len(data)} 个、"
            f"合计 {round(sum(totals.values()), 2)}"
        )
        return data
    except Exception as exc:  # noqa: BLE001 - 账龄失败不阻断订单类指标
        logger.warning(f"账龄取数失败（{period_value}）：{exc}")
        return {}


# --------------------------------------------------------------------------- #
# 取值工具
# --------------------------------------------------------------------------- #
def to_number(value: Any) -> float:
    if value is None or value == "" or value == "-":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def money(value: float) -> float:
    return round(float(value or 0), 4)


def percent(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 4)


async def _latest_run_rows(db: AsyncSession, object_code: str) -> list[dict]:
    """取某来源对象最近一次成功批次的明细行。"""
    # 先只取批次 id（rows_json 体量大，直接参与 ORDER BY 会触发 MySQL「Out of sort memory」）
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
        await db.execute(
            select(MetaSyncRunModel.rows_json).where(MetaSyncRunModel.id == run_id)
        )
    ).scalars().first()
    return list(extract_payload_rows(rows) or [])


def product_line_map(rows: list[dict]) -> dict[int, str]:
    """``product_series`` 编码 → 产品线大类名称。

    上卷规则（方案 §7 第 3 条）：沿父链上卷到「产品分类」下的一级节点；
    若一级节点是容器（未知/其它/新产品），再下沉一层取具体子类（钣金外壳 / CNC外壳 / 面板…）。
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
        path.reverse()  # [一级, …, node]
        if not path:
            return ""
        top = path[0]
        if name.get(top) in CONTAINER_PRODUCT_NAMES and len(path) > 1:
            return name.get(path[1], "")
        return name.get(top, "")

    return {node: resolve(node) for node in parent if node != PRODUCT_CATEGORY_ROOT_ID}


async def _order_region_index(db: AsyncSession) -> dict[str, str]:
    """订单号 → 地区（内贸 region / 外贸 country），取自 CRM 订单明细批次。"""
    index: dict[str, str] = {}
    for object_code in (ORDER_OBJECT_DOMESTIC, ORDER_OBJECT_EXPORT):
        for row in await _latest_run_rows(db, object_code):
            number = str(row.get("number") or "").strip()
            if not number:
                continue
            for key in REGION_KEYS:
                value = str(row.get(key) or "").strip()
                if value:
                    index[number] = value
                    break
    return index


async def _company_metric_totals(db: AsyncSession, period_value: str) -> dict[str, float]:
    """取公司合计层的分摊基数（REV-01 / CM-01 / CM-04 / PER-02，期间最新版本）。"""
    codes = list(COMPANY_METRIC_CODES.values())
    rows = (
        await db.execute(
            select(MetricDefModel.code, MetricValueModel.value, MetricValueModel.calc_version)
            .join(MetricValueModel, MetricValueModel.metric_id == MetricDefModel.id)
            .where(
                MetricDefModel.code.in_(codes),
                MetricValueModel.period_value == period_value,
                MetricValueModel.org_id.is_(None),
                MetricValueModel.dept_id.is_(None),
                MetricValueModel.person_id.is_(None),
            )
        )
    ).all()
    latest: dict[str, tuple[int, float]] = {}
    for code, value, calc_version in rows:
        version = int(calc_version or 1)
        if code not in latest or version >= latest[code][0]:
            latest[code] = (version, to_number(value))
    by_code = {code: item[1] for code, item in latest.items()}
    return {label: by_code.get(code, 0.0) for label, code in COMPANY_METRIC_CODES.items()}


async def _load_ar_customer_rows(db: AsyncSession, period_value: str) -> dict[str, dict[str, float]]:
    """取客户维度的应收余额 / 逾期应收（``metric_value.dept_code`` = 客户编号，取最新版本）。

    用途：让「本月没有交易、但有应收余额/账龄」的客户也能出现在客户分析表里，
    否则欠款客户的欠款会整月消失。
    """
    rows = (
        await db.execute(
            select(
                MetricDefModel.code,
                MetricValueModel.dept_code,
                MetricValueModel.dept_name,
                MetricValueModel.value,
                MetricValueModel.calc_version,
            )
            .join(MetricValueModel, MetricValueModel.metric_id == MetricDefModel.id)
            .where(
                MetricDefModel.code.in_(AR_METRIC_CODES),
                MetricValueModel.period_value == period_value,
                MetricValueModel.dept_code.is_not(None),
            )
        )
    ).all()
    latest: dict[str, int] = {}
    for code, _dept_code, _dept_name, _value, calc_version in rows:
        version = int(calc_version or 1)
        if version > latest.get(code, 0):
            latest[code] = version
    result: dict[str, dict[str, float]] = {}
    for code, dept_code, dept_name, value, calc_version in rows:
        if int(calc_version or 1) != latest.get(code):
            continue
        item = result.setdefault(str(dept_code), {"CUS-21": 0.0, "CUS-22": 0.0, "name": dept_name or ""})
        if code == AR_BALANCE_CODE:
            item["CUS-21"] = to_number(value)
        elif code == AR_OVERDUE_CODE:
            item["CUS-22"] = to_number(value)
    return result


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


def _concat(counter: dict[str, float]) -> str:
    """多值拼接：按金额降序，金额相同按名称升序，``/`` 分隔，空值不参与。"""
    items = [(key, value) for key, value in counter.items() if key]
    items.sort(key=lambda item: (-item[1], item[0]))
    return "/".join(key for key, _value in items)


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #
async def build_period(db: AsyncSession, period_value: str) -> dict[str, Any]:
    """构建某期间的客户分析宽表，返回构建结果。"""
    started = datetime.now(UTC)
    order_rows, order_version = await _latest_order_rows(db, period_value)
    master_rows = await _latest_run_rows(db, CUSTOMER_MASTER_OBJECT)
    product_rows = await _latest_run_rows(db, PRODUCT_DICT_OBJECT)
    lines = product_line_map(product_rows)
    regions = await _order_region_index(db)
    company = await _company_metric_totals(db, period_value)
    ar_rows = await _load_ar_customer_rows(db, period_value)
    aging_rows = await _load_aging_rows(period_value)
    person_index = await _load_person_index(db)

    master: dict[int, dict] = {}
    for row in master_rows:
        try:
            master[int(row.get("id"))] = row
        except (TypeError, ValueError):
            continue

    version = int(
        (
            await db.execute(
                select(func.max(CustomerAnalysisModel.calc_version)).where(
                    CustomerAnalysisModel.period_value == period_value
                )
            )
        ).scalar()
        or 0
    ) + 1

    run = CustomerBuildRunModel(
        period_value=period_value,
        calc_version=version,
        status="running",
        warnings=list(PENDING_NOTES),
        master_customer_count=len(master),
        started_at=started,
    )
    db.add(run)
    await db.flush()

    buckets: dict[Any, dict[str, Any]] = {}
    for row in order_rows:
        extra = row.extra or {}
        key = row.customer_id or extra.get("customer_number") or row.customer_name or 0
        bucket = buckets.setdefault(
            key,
            {
                "customer_id": row.customer_id,
                "customer_code": str(extra.get("customer_number") or "") or None,
                "customer_name": str(extra.get("customer_name") or "") or None,
                "salesman_code": str(row.salesman_code or "") or None,
                "salesman_name": str(extra.get("salesman_name") or "") or None,
                "order_type_counter": {},
                "product_line_counter": {},
                "sku_counter": {},
                "trade_counter": {},
                "region_counter": {},
                "category_counter": {},
                "term_counter": {},
                "salesman_counter": {},
                "ar_balance": 0.0,
                "ar_overdue": 0.0,
                "aging": {},
                "ar_only": False,
                "customer_category": None,
                "collection_term": None,
                "order_count": 0,
                "repeat_order_count": 0,
                "intake_untaxed": 0.0,
                "ship_untaxed": 0.0,
                "design_income": 0.0,
                "return_refund": 0.0,
                "gross_profit": 0.0,
                "contribution_margin": 0.0,
            },
        )
        bucket["order_count"] += 1
        if str(extra.get("is_new_code") or extra.get("is_new") or "") == "2":
            bucket["repeat_order_count"] += 1
        bucket["intake_untaxed"] += to_number(row.intake_untaxed)
        bucket["ship_untaxed"] += to_number(row.ship_untaxed)
        bucket["design_income"] += to_number(extra.get("design_service_income"))
        bucket["return_refund"] += to_number(extra.get("return_refund"))
        bucket["gross_profit"] += to_number(extra.get("gross_profit"))
        bucket["contribution_margin"] += to_number(extra.get("contribution_margin"))

        raw_order_type = str(extra.get("order_type") or row.order_type or "").strip()
        order_type = ORDER_TYPE_NAMES.get(raw_order_type, raw_order_type)
        bucket["order_type_counter"][order_type] = bucket["order_type_counter"].get(order_type, 0.0) + to_number(row.intake_untaxed)
        series = extra.get("product_series_id") or extra.get("product_series")
        try:
            line_name = lines.get(int(series), "") if series not in (None, "") else ""
        except (TypeError, ValueError):
            line_name = ""
        if line_name:
            bucket["product_line_counter"][line_name] = bucket["product_line_counter"].get(line_name, 0.0) + to_number(row.intake_untaxed)
        sku = str(extra.get("sku") or "").strip()
        if sku:
            bucket["sku_counter"][sku] = bucket["sku_counter"].get(sku, 0.0) + to_number(row.intake_untaxed)
        trade = TRADE_NAMES.get(str(row.trade_type or ""), str(row.trade_type or ""))
        bucket["trade_counter"][trade] = bucket["trade_counter"].get(trade, 0.0) + to_number(row.intake_untaxed)
        region = str(regions.get(str(row.order_number)) or "").strip()
        if region:
            bucket["region_counter"][region] = bucket["region_counter"].get(region, 0.0) + to_number(row.intake_untaxed)
        category = str(extra.get("customer_category") or "").strip()
        if category:
            bucket["category_counter"][category] = bucket["category_counter"].get(category, 0.0) + 1
        term = str(extra.get("collection_term") or "").strip()
        if term:
            bucket["term_counter"][term] = bucket["term_counter"].get(term, 0.0) + 1
        # 业务员按姓名展示（同一客户当月多个业务员时按金额降序拼接）
        salesman_name = str(extra.get("salesman_name") or "").strip()
        if salesman_name:
            bucket["salesman_counter"][salesman_name] = bucket["salesman_counter"].get(
                salesman_name, 0.0
            ) + to_number(row.intake_untaxed)

    # 并入「本月没有交易、但有应收余额 / 逾期应收」的客户（否则欠款客户的欠款整月消失）
    bucket_by_code = {
        str(bucket["customer_code"]): bucket for bucket in buckets.values() if bucket.get("customer_code")
    }
    master_by_code = {str(row.get("number")): row for row in master_rows if row.get("number")}
    for code, ar in ar_rows.items():
        if not code:
            continue
        bucket = bucket_by_code.get(code)
        if bucket is None:
            master_row = master_by_code.get(code) or {}
            principal = master_row.get("principal_id")
            principal_meta = person_index.get(str(principal)) if principal not in (None, "") else None
            bucket = {
                "customer_id": master_row.get("id"),
                "customer_code": code,
                "customer_name": str(ar.get("name") or master_row.get("name") or "") or None,
                "salesman_code": str(principal) if principal not in (None, "") else None,
                "salesman_name": (principal_meta or {}).get("person_name"),
                "order_type_counter": {},
                "product_line_counter": {},
                "sku_counter": {},
                "trade_counter": {},
                "region_counter": {},
                "category_counter": {},
                "term_counter": {},
                "salesman_counter": {},
                "ar_balance": 0.0,
                "ar_overdue": 0.0,
                "aging": {},
                "ar_only": True,
                "customer_category": None,
                "collection_term": None,
                "order_count": 0,
                "repeat_order_count": 0,
                "intake_untaxed": 0.0,
                "ship_untaxed": 0.0,
                "design_income": 0.0,
                "return_refund": 0.0,
                "gross_profit": 0.0,
                "contribution_margin": 0.0,
            }
            buckets[f"ar:{code}"] = bucket
            bucket_by_code[code] = bucket
            if bucket["salesman_name"]:
                bucket["salesman_counter"][bucket["salesman_name"]] = 0.0
        bucket["ar_balance"] = ar.get("CUS-21", 0.0)
        bucket["ar_overdue"] = ar.get("CUS-22", 0.0)
        bucket["customer_code"] = bucket["customer_code"] or code

    # 并入账龄客户（CUS-24~27）：本月无交易、也无应收余额台账但有账龄的客户同样要出现
    for code, aging in aging_rows.items():
        if not code:
            continue
        bucket = bucket_by_code.get(code)
        if bucket is None:
            master_row = master_by_code.get(code) or {}
            principal = master_row.get("principal_id")
            principal_meta = person_index.get(str(principal)) if principal not in (None, "") else None
            bucket = {
                "customer_id": master_row.get("id"),
                "customer_code": code,
                "customer_name": str(aging.get("name") or master_row.get("name") or "") or None,
                "salesman_code": str(principal) if principal not in (None, "") else None,
                "salesman_name": (principal_meta or {}).get("person_name"),
                "order_type_counter": {},
                "product_line_counter": {},
                "sku_counter": {},
                "trade_counter": {},
                "region_counter": {},
                "category_counter": {},
                "term_counter": {},
                "salesman_counter": {},
                "ar_balance": 0.0,
                "ar_overdue": 0.0,
                "aging": {},
                "ar_only": True,
                "customer_category": None,
                "collection_term": None,
                "order_count": 0,
                "repeat_order_count": 0,
                "intake_untaxed": 0.0,
                "ship_untaxed": 0.0,
                "design_income": 0.0,
                "return_refund": 0.0,
                "gross_profit": 0.0,
                "contribution_margin": 0.0,
            }
            if bucket["salesman_name"]:
                bucket["salesman_counter"][bucket["salesman_name"]] = 0.0
            buckets[f"aging:{code}"] = bucket
            bucket_by_code[code] = bucket
        bucket["aging"] = aging
        bucket["customer_code"] = bucket["customer_code"] or code

    records: list[CustomerAnalysisModel] = []
    total_intake = total_net = total_gross = total_contribution = 0.0
    total_orders = 0
    rev01 = company.get("REV-01", 0.0)

    for bucket in buckets.values():
        master_row = master.get(int(bucket["customer_id"])) if bucket["customer_id"] else None
        if master_row:
            bucket["customer_code"] = bucket["customer_code"] or str(master_row.get("number") or "")
            bucket["customer_name"] = bucket["customer_name"] or str(master_row.get("name") or "")
        # 地区以客户主档为准（内贸取 region 省市县，外贸取 country 国家），订单行为兜底
        master_type = str((master_row or {}).get("type") or "").strip()
        region_value = ""
        if master_type == "1":
            region_value = str((master_row or {}).get("region") or "").strip()
        elif master_type == "2":
            region_value = str((master_row or {}).get("country") or "").strip()
        region_value = region_value or _concat(bucket["region_counter"])
        trade_value = _concat(bucket["trade_counter"]) or MASTER_TYPE_NAMES.get(master_type, "")
        intake = money(bucket["intake_untaxed"])
        net_shipment = money(bucket["ship_untaxed"] + bucket["design_income"] + bucket["return_refund"])
        gross_profit = money(bucket["gross_profit"])
        settlement_income = money(net_shipment * SETTLEMENT_RATE)
        share = (net_shipment / rev01) if rev01 else 0.0
        contribution = money(
            settlement_income - share * company.get("CM-01", 0.0)
        )
        settlement_profit = money(
            contribution - share * company.get("CM-04", 0.0) - share * company.get("PER-02", 0.0)
        )
        net_abs = abs(net_shipment)
        extra_out: dict[str, Any] = {
            "CUS-00": period_value,
            "CUS-01": bucket["customer_code"],
            "CUS-02": bucket["customer_name"],
            "CUS-03": bucket["customer_category"] or _concat(bucket["category_counter"]),
            "CUS-04": region_value,
            "CUS-05": trade_value,
            "CUS-08": _concat(bucket["salesman_counter"]) or bucket["salesman_name"],
            "CUS-09": _concat(bucket["product_line_counter"]),
            "CUS-10": _concat(bucket["sku_counter"]),
            "CUS-11": _concat(bucket["order_type_counter"]),
            "CUS-12": intake,
            "CUS-13": money(bucket["ship_untaxed"]),
            "CUS-14": money(bucket["design_income"]),
            "CUS-15": money(bucket["return_refund"]),
            "CUS-16": net_shipment,
            "CUS-17": settlement_income,
            "CUS-21": money(bucket["ar_balance"]) or None,
            "CUS-22": money(bucket["ar_overdue"]) or None,
            "CUS-23": percent(bucket["ar_overdue"], bucket["ar_balance"]),
            "CUS-24": (bucket["aging"] or {}).get("CUS-24"),
            "CUS-25": (bucket["aging"] or {}).get("CUS-25"),
            "CUS-26": (bucket["aging"] or {}).get("CUS-26"),
            "CUS-27": (bucket["aging"] or {}).get("CUS-27"),
            "CUS-28": gross_profit,
            "CUS-29": percent(gross_profit, net_shipment),
            "CUS-30": contribution,
            "CUS-31": percent(contribution, settlement_income),
            "CUS-32": settlement_profit,
            "CUS-33": percent(settlement_profit, settlement_income),
            "CUS-35": percent(settlement_profit, rev01),
            "CUS-40": percent(bucket["repeat_order_count"], bucket["order_count"]),
            "CUS-41": percent(abs(money(bucket["return_refund"])), net_abs),
            "CUS-42": round(intake / bucket["order_count"], 4) if bucket["order_count"] else 0.0,
            "CUS-47": bucket["order_count"],
            "salesman_name": bucket["salesman_name"],
            "salesman_code": bucket["salesman_code"],
            "order_type_code": None,
            "repeat_order_count": bucket["repeat_order_count"],
            "collection_term_raw": _concat(bucket["term_counter"]),
            "buy_frequency_year": (master_row or {}).get("buy_frequency_year"),
        }
        records.append(
            CustomerAnalysisModel(
                period_value=period_value,
                calc_version=version,
                is_aggregate=0,
                customer_id=bucket["customer_id"],
                customer_code=bucket["customer_code"],
                customer_name=bucket["customer_name"],
                salesman_code=bucket["salesman_code"],
                salesman_name=bucket["salesman_name"],
                order_count=bucket["order_count"],
                intake_untaxed=intake,
                net_shipment=net_shipment,
                gross_profit=gross_profit,
                contribution_margin=contribution,
                extra=extra_out,
                data_quality_flag=(
                    "ar_only" if bucket["ar_only"] else ("ok" if bucket["customer_id"] else "customer_unmapped")
                ),
            )
        )
        total_intake += intake
        total_net += net_shipment
        total_gross += gross_profit
        total_contribution += contribution
        total_orders += bucket["order_count"]

    # 合计行（客户编码留空）：总客户数按底稿取客户主档时点总数
    aggregate_extra: dict[str, Any] = {
        "CUS-00": period_value,
        "CUS-43": len(master),
        "CUS-12": money(total_intake),
        "CUS-16": money(total_net),
        "CUS-17": money(total_net * SETTLEMENT_RATE),
        "CUS-28": money(total_gross),
        "CUS-30": money(total_contribution),
        "CUS-47": total_orders,
        "master_customer_count": len(master),
    }
    records.append(
        CustomerAnalysisModel(
            period_value=period_value,
            calc_version=version,
            is_aggregate=1,
            customer_id=None,
            customer_code=None,
            customer_name="合计",
            order_count=total_orders,
            intake_untaxed=money(total_intake),
            net_shipment=money(total_net),
            gross_profit=money(total_gross),
            contribution_margin=money(total_contribution),
            extra=aggregate_extra,
            data_quality_flag="aggregate",
        )
    )

    db.add_all(records)
    run.status = "success"
    run.customer_count = len(records) - 1
    run.order_count = total_orders
    run.intake_untaxed_sum = money(total_intake)
    run.net_shipment_sum = money(total_net)
    run.finished_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        f"客户分析构建完成 {period_value} v{version}：客户 {run.customer_count} 个、"
        f"订单 {total_orders} 单、接单未税 {money(total_intake)}"
    )
    return {
        "period_value": period_value,
        "calc_version": version,
        "customer_count": run.customer_count,
        "order_count": total_orders,
        "intake_untaxed_sum": money(total_intake),
        "net_shipment_sum": money(total_net),
        "master_customer_count": len(master),
        "order_source_version": order_version,
        "company_base": company,
        "warnings": list(PENDING_NOTES),
    }
