"""指标计算引擎。

配置化执行：``metric_def.measures`` / ``metric_def.dimensions`` 描述取数规则，
引擎只解释配置、不写死业务字段。v1 支持:

- ``kind = account_balance_filter``：金蝶科目余额表（``GL_RPT_AccountBalance``）。
  该报表是「科目行 + 核算维度行」两级结构：科目行带科目编码，紧随其后的核算维度行
  科目列为空、必须继承上一科目行。按科目与核算维度过滤后聚合指定金额字段。
  可用 ``measures.org_codes`` 限定只取某几个组织（如 ``["100"]``），
  缺省取该来源对象下全部启用组织的同步任务。

- ``kind = production_instock_amount``：金蝶生产入库单（``PRD_INSTOCK``，``ExecuteBillQuery``）。
  按「需求单据前缀（如 BH 备货订单）」过滤本期生产入库单，回查生产订单（``PRD_MO``）的
  单据头 ``F_UIVG_Decimal_83g``（Y订单金额）、物料与生产数量：物料含 ``C.`` 的订单
  （半成品，常分多分录/多次入库）当月只计一次整单金额，其余订单按单价结转
  （单价 = Y订单金额 ÷ 生产数量，金额 = Σ(入库数量 × 单价)）。

- ``kind = metric_sum`` / ``metric_scale`` / ``metric_ratio`` / ``metric_diff`` /
  ``metric_balance_avg``：派生指标，自身不取数，值由既有指标的当期结果计算得出——
  合计（当期各组成指标之和）、折算（合计 × ``scale``）、
  比率（分子合计 ÷ 分母合计 × ``ratio_scale``；分子/分母还可用
  ``numerator_subtrahend_metric_codes`` / ``denominator_subtrahend_metric_codes`` 声明减项，
  即「加项之和 − 减项之和」，如安全边际率 =（总收益 − 盈亏平衡点销售额）÷ 总收益）、
  差额（加项合计 − 减项合计，如边际贡献 = 总收益 − 变动费用合计）、
  期初期末平均（上一期合计 × ``begin_weight`` + 当期合计 × ``end_weight``，默认各 0.5，
  即「（期初 + 期末）÷ 2」，如上期无结果按 0 计入）。

- ``kind = ar_aging_provision``：金蝶《应收款账龄分析表》（``AR_AgingAnalysis``）按单据
  取「尚未收款金额（本位币）＋业务日期/到期日」，按配置的账龄区间比例计提坏账准备。
  该报表不在同步批次里落库（一次全量约 7MB/组织），改为计算时按组织实时取数。

- ``kind = inventory_ledger_balance``：金蝶《存货收发存汇总表》
  （``HS_INOUTSTOCKSUMMARYRPT``）。报表按「核算体系 + 核算组织 + 会计政策 + 会计期间 +
  仓库区间」过滤（同期数据由同步任务落批次），计算时汇总期末结存金额 ``FENDAmount``
  （取数量口径改 ``amount_field = FENDQty``）。报表同时返回明细行与小计行，小计行
  仓库列为空、物料编码带 ``-总计``，引擎按此跳过，避免重复计入。

计算结果是「期间 + 组织 + 部门」粒度的指标值；同一期间每天重算时
``calc_version`` 递增并保留历史行，查询默认取最新版本。
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from app.core.database import async_db_session
from app.core.logger import logger
from app.modules.crm.org_person import CRM_SOURCE_TYPE
from app.modules.erp.jushuitan.aggregate import summarize as summarize_outbound_amount
from app.modules.erp.kingdee.client import KingdeeBillQueryRequest
from app.modules.erp.kingdee.model import KingdeeConnectionModel
from app.modules.erp.kingdee.service import KingdeeService
from app.modules.masterdata.model import MasterDeptModel, MasterOrgModel, MasterPersonModel, SourcePersonModel
from app.modules.metadata.model import (
    MetaSyncJobModel,
    MetaSyncRunModel,
    SourceObjectModel,
    SourceSystemModel,
)
from app.modules.metadata.sync import (
    execute_meta_sync_job,
    fetch_report_data,
    merge_variables,
    render_request_params,
    resolve_period_datetime,
)

from .model import MetricDefModel, MetricRunModel, MetricValueModel

ACCOUNT_BALANCE_KIND = "account_balance_filter"
# 指标汇总：自身不取数，值为若干既有指标当期值之和
METRIC_SUM_KIND = "metric_sum"
# 指标折算：自身不取数，值为「既有指标当期值之和 × scale 系数」（如总收益 = 净额 × 10%）
METRIC_SCALE_KIND = "metric_scale"
# 指标比率：自身不取数，值为「分子指标当期值之和 ÷ 分母指标当期值之和 × ratio_scale」
# （如下推率 = 下推金额 ÷ 接单金额；分母为 0 时取 0，避免除零）
METRIC_RATIO_KIND = "metric_ratio"
# 业务员比率：分子 / 分母都是**业务员维度**指标，按业务员分别相除
# （如复购率 = 本月下单老客户数 ÷ 总客户数、客单价 = 接单未税 ÷ 订单数）
METRIC_RATIO_PERSON_KIND = "metric_ratio_person"
# 指标期初期末平均：自身不取数，值为「上期组成指标合计 × begin_weight + 当期组成指标合计 × end_weight」
# （如平均库存 =（期初 + 期末）÷ 2；期初取上一期该指标的结果，上期无结果按 0 计入）
METRIC_BALANCE_AVG_KIND = "metric_balance_avg"
# 指标差额：自身不取数，值为「加项指标当期值之和 − 减项指标当期值之和」
# （如边际贡献 = 总收益（营销结算收入）− 变动费用合计）
METRIC_DIFF_KIND = "metric_diff"
SALES_OUTBOUND_KIND = "sales_outbound_amount"
API_SCALAR_KIND = "api_scalar_amount"
PRODUCTION_INSTOCK_KIND = "production_instock_amount"
# 应收款账龄计提：来源是《应收款账龄分析表》，数据量大且只用于计算，改为实时取数不落批次
AR_AGING_KIND = "ar_aging_provision"
# 存货收发存：来源是金蝶《存货收发存汇总表》（HS_INOUTSTOCKSUMMARYRPT），按仓库过滤后汇总期末结存
INVENTORY_LEDGER_KIND = "inventory_ledger_balance"
# 单据金额：金蝶单据查询（ExecuteBillQuery）按行过滤后汇总金额；支持多来源对象组成一个合计指标
BILL_AMOUNT_KIND = "bill_amount_filter"
# 业务员明细：CRM 订单明细（orderAnalyze）按业务员（下单人 create_id）分组汇总金额
CRM_PERSON_AMOUNT_KIND = "crm_person_amount"
# 业务员明细：CRM 发货明细（orderShipments）关联订单明细取业务员与未税单价，按业务员汇总出货未税金额
CRM_SHIPMENT_PERSON_AMOUNT_KIND = "crm_shipment_person_amount"
# 业务员明细：CRM 订单明细按「ERP 下推时间」落在当期过滤，按业务员汇总下推金额 / 平均下推周期
CRM_ORDER_PUSH_PERSON_KIND = "crm_order_push_person"
# 业务员明细：CRM 报价单明细按业务员汇总报价次数 / 报价成功率 / 报价毛利率
CRM_QUOTE_PERSON_KIND = "crm_quote_person"
# 业务员维度的取数类型（结果行带 person_code，含公司合计行）
CRM_PERSON_KINDS = (
    CRM_PERSON_AMOUNT_KIND,
    CRM_SHIPMENT_PERSON_AMOUNT_KIND,
    CRM_ORDER_PUSH_PERSON_KIND,
    CRM_QUOTE_PERSON_KIND,
)
METRIC_SUM_KIND = "metric_sum"
SUPPORTED_KINDS = {
    ACCOUNT_BALANCE_KIND,
    SALES_OUTBOUND_KIND,
    API_SCALAR_KIND,
    PRODUCTION_INSTOCK_KIND,
    AR_AGING_KIND,
    INVENTORY_LEDGER_KIND,
    BILL_AMOUNT_KIND,
    METRIC_SUM_KIND,
    METRIC_SCALE_KIND,
    METRIC_RATIO_KIND,
    METRIC_DIFF_KIND,
    METRIC_BALANCE_AVG_KIND,
    METRIC_RATIO_PERSON_KIND,
    CRM_PERSON_AMOUNT_KIND,
    CRM_SHIPMENT_PERSON_AMOUNT_KIND,
    CRM_ORDER_PUSH_PERSON_KIND,
    CRM_QUOTE_PERSON_KIND,
}
# 计算时实时取数、不依赖同步批次的取数类型
LIVE_KINDS = {AR_AGING_KIND}
# 账龄计提默认区间：账龄天数 ≤ max_days 的档位比例（max_days 为 None 表示兜底档）
DEFAULT_AGING_BUCKETS = [
    {"max_days": 30, "rate": 0.0},
    {"max_days": 60, "rate": 0.05},
    {"max_days": 90, "rate": 0.10},
    {"max_days": 180, "rate": 0.20},
    {"max_days": 365, "rate": 0.50},
    {"max_days": None, "rate": 1.0},
]


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #
def _parse_amount(value: Any) -> float:
    """金蝶报表金额是带千分位的字符串（``"1,286.51"`` / ``""`` / ``None``）。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _field_order(request_params: dict | None) -> list[str]:
    """从同步任务的请求参数里取字段顺序（报表 Rows 是值数组，不含表头）。"""
    raw = (request_params or {}).get("FieldKeys")
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _payload_rows(payload: dict | None) -> list | None:
    """兼容金蝶 ``Rows``、聚水潭 ``datas`` 与 CRM ``data``（明细数组）三种返回结构；缺失返回 ``None``。"""
    if not isinstance(payload, dict):
        return None
    rows = payload.get("Rows") if isinstance(payload.get("Rows"), list) else payload.get("datas")
    if isinstance(rows, list):
        return rows
    # CRM 明细接口（orderAnalyze / orderShipments）业务数据直接放在 ``data`` 数组里
    data = payload.get("data")
    return data if isinstance(data, list) else None


def _cell(row: Any, fields: list[str], key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    if not fields:
        return None
    try:
        index = fields.index(key)
    except ValueError:
        return None
    return row[index] if index < len(row) else None


def _config_signature(config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# 派生指标引用其他指标的字段（按 kind）；与 ``_load_metric_context`` 的分组解析同源
METRIC_DEPENDENCY_FIELDS: dict[str, tuple[str, ...]] = {
    METRIC_SUM_KIND: ("component_metric_codes",),
    METRIC_SCALE_KIND: ("component_metric_codes",),
    METRIC_BALANCE_AVG_KIND: ("component_metric_codes",),
    METRIC_RATIO_KIND: (
        "numerator_metric_codes",
        "numerator_subtrahend_metric_codes",
        "denominator_metric_codes",
        "denominator_subtrahend_metric_codes",
    ),
    METRIC_RATIO_PERSON_KIND: (
        "numerator_metric_codes",
        "denominator_metric_codes",
    ),
    METRIC_DIFF_KIND: ("addend_metric_codes", "subtrahend_metric_codes"),
}

# 指标调度与 calc_time 「当天已算过」判断统一按 Asia/Shanghai 切分
CN_TZ = ZoneInfo("Asia/Shanghai")

# 单次计算内的指标调用链（ContextVar 随 asyncio 任务传递）：用于识别环形依赖，避免无限递归
CALC_CHAIN: ContextVar[tuple[int, ...]] = ContextVar("metric_calc_chain", default=())


def _normalize_metric_codes(raw: Any) -> list[str]:
    """把 ``component_metric_codes`` 之类的配置归一为去空的编码列表（兼容单字符串）。"""
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


def metric_dependency_codes(measures: dict | None) -> list[str]:
    """派生指标依赖的组成指标编码（去重、保持声明顺序）；非派生指标返回空列表。

    ``metric_sum`` / ``metric_scale`` / ``metric_balance_avg`` 取 ``component_metric_codes``；
    ``metric_ratio`` 取分子分母及其各自减项；``metric_diff`` 取加项与减项。
    调度分批（``batch.py``）与运行期解析（``_load_metric_context``）共用本函数，
    保证「排期顺序」与「实际取数口径」同源，不会各自漂移。
    """
    config = measures or {}
    kind = str(config.get("kind") or "")
    codes: list[str] = []
    for field in METRIC_DEPENDENCY_FIELDS.get(kind, ()):
        codes.extend(_normalize_metric_codes(config.get(field)))
    return list(dict.fromkeys(codes))


def _as_utc(value: datetime) -> datetime:
    """统一成带时区的 UTC；数据库若返回 naive datetime 按 UTC 解释。"""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def local_day_start(now: datetime | None = None) -> datetime:
    """返回「当天 00:00（Asia/Shanghai）」对应的 UTC 时刻，作为「今天已算过」的判定线。"""
    local = _as_utc(now or datetime.now(UTC)).astimezone(CN_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def current_period_value(period_type: str, today: date | None = None) -> str:
    """按期间类型返回当前期间值（月指标 → ``2026-09``）。"""
    today = today or date.today()
    if period_type == "day":
        return today.strftime("%Y-%m-%d")
    if period_type == "year":
        return today.strftime("%Y")
    return today.strftime("%Y-%m")


def previous_period_value(period_type: str, today: date | None = None) -> str:
    """按期间类型返回上一个期间值（月指标 → 上月 ``YYYY-MM``）。

    月指标需要「次月 1 日重算上月」：每日 02:30 的重算只覆盖当月，
    月末最后一天白天产生的出库单不会被算进去，必须在次月 1 日补一次。
    """
    today = today or date.today()
    if period_type == "day":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if period_type == "year":
        return str(today.year - 1)
    return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def shift_period(period_type: str, period_value: str, steps: int = -1) -> str:
    """按期间类型把期间值前后平移（月指标：``2026-09`` + (-1) → ``2026-08``）。

    用于「期初 = 上一期结果」这类口径（如平均库存 =（期初 + 期末）÷ 2）。
    """
    moment = resolve_period_datetime(period_value)
    if moment is None:
        raise ValueError(f"期间值格式不支持: {period_value}")
    if period_type == "day":
        return (moment + timedelta(days=steps)).strftime("%Y-%m-%d")
    if period_type == "year":
        return str(moment.year + steps)
    # 月指标：按「月初 + steps 个月」平移，避免月末天数差异
    month_index = moment.year * 12 + (moment.month - 1) + steps
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


# --------------------------------------------------------------------------- #
# 科目余额表取数执行器
# --------------------------------------------------------------------------- #
def extract_account_balance(rows: list, fields: list[str], config: dict) -> dict:
    """从科目余额表行中按配置过滤并聚合。

    配置项（``measures``）:
    - ``account_field`` / ``account_prefix``：科目编码字段与匹配前缀，如 ``FBALANCEID`` + ``6601``。
    - ``detail_code_field`` / ``detail_name_field``：核算维度编码与名称字段。
    - ``detail_name_contains``：核算维度名称需包含的关键字（任一命中即计入）。
    - ``detail_name_exclude``：核算维度名称命中即**排除**的关键字，用于关键字互为子串的场景
      （如「维修费」会命中「车辆维修费」，需把车辆维修费排除在维修费指标外）。
    - ``amount_field``：金额字段，如 ``FDEBIT``（本期借方发生额）。
    - ``amount_terms``：多字段组合取值，如期末余额 = ``[{"field": "FENDDEBIT", "sign": 1},
      {"field": "FENDCREDIT", "sign": -1}]``（借方减贷方）；配置后优先于 ``amount_field``。
    - ``detail_code_exclude_in``：核算维度编码命中即排除（如应收账款剔除组织 100-113 的内部客户）。
    - ``require_detail``：为真时跳过没有核算维度编码/名称的行（科目汇总行），避免与明细重复计入。
    - ``detail_is_department``：维度是否为部门（默认 True）。费用类指标按「部门/费用项目」拆分部门；
      客户类指标（如应收余额）为 False，直接以维度名称作为明细名称。

    返回:
    - dict: ``total`` 合计值、``departments`` 按部门（核算维度编码 ``/`` 前段）明细、``matched_rows`` 命中行数。
    """
    account_field = str(config.get("account_field") or "FBALANCEID")
    account_prefix = str(config.get("account_prefix") or "")
    detail_code_field = str(config.get("detail_code_field") or "FDETAILNUMBER")
    detail_name_field = str(config.get("detail_name_field") or "FDETAILNAME")
    amount_field = str(config.get("amount_field") or "FDEBIT")
    amount_terms = config.get("amount_terms")
    terms: list[tuple[str, float]] = []
    if isinstance(amount_terms, list):
        for term in amount_terms:
            if isinstance(term, dict) and term.get("field"):
                terms.append((str(term["field"]), float(term.get("sign", 1))))
    if not terms:
        terms = [(amount_field, 1.0)]
    code_exclude = config.get("detail_code_exclude_in") or []
    if isinstance(code_exclude, str):
        code_exclude = [code_exclude]
    code_exclude = {str(item).strip() for item in code_exclude if str(item).strip()}
    require_detail = bool(config.get("require_detail"))
    is_dept_dim = bool(config.get("detail_is_department", True))
    keywords = config.get("detail_name_contains") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [str(item).strip() for item in keywords if str(item).strip()]
    exclude = config.get("detail_name_exclude") or []
    if isinstance(exclude, str):
        exclude = [exclude]
    exclude = [str(item).strip() for item in exclude if str(item).strip()]

    total = 0.0
    matched_rows = 0
    departments: dict[str, dict[str, Any]] = {}
    current_account = ""
    for row in rows:
        account = _cell(row, fields, account_field)
        account = str(account).strip() if account is not None else ""
        if account:
            current_account = account
        if account_prefix and not current_account.startswith(account_prefix):
            continue
        detail_code_raw = str(_cell(row, fields, detail_code_field) or "").strip()
        detail_name = str(_cell(row, fields, detail_name_field) or "").strip()
        if require_detail and not detail_code_raw and not detail_name:
            continue
        parts = [part.strip() for part in detail_code_raw.split("/") if part.strip()]
        if code_exclude and parts and parts[0] in code_exclude:
            continue
        if keywords and not any(keyword in detail_name for keyword in keywords):
            continue
        if exclude and any(keyword in detail_name for keyword in exclude):
            continue
        amount = sum(sign * _parse_amount(_cell(row, fields, field)) for field, sign in terms)
        total += amount
        matched_rows += 1
        if is_dept_dim:
            # 核算维度可能是「部门/费用项目」或只有「费用项目」（如 GY.88 快递费）：
            # 后者没有部门归属，单独归到「未指定部门」，不要把费用项目名当部门名。
            dept_code = parts[0] if parts else detail_name
            dept_name = detail_name.split("/")[0].strip() if "/" in detail_name else "未指定部门"
        else:
            dept_code = detail_code_raw or detail_name
            dept_name = detail_name or detail_code_raw
        bucket = departments.setdefault(dept_code, {"name": dept_name, "value": 0.0, "rows": 0})
        bucket["value"] = round(float(bucket["value"]) + amount, 4)
        bucket["rows"] = int(bucket["rows"]) + 1
    return {"total": round(total, 4), "departments": departments, "matched_rows": matched_rows}


def _row_matches_filters(row: Any, fields: list[str], filters: Any) -> bool:
    """单据行是否命中全部过滤条件（``row_filters`` 每项 ``{field, op, value|values}``）。"""
    if not isinstance(filters, list):
        return True
    for flt in filters:
        if not isinstance(flt, dict):
            continue
        field = str(flt.get("field") or "")
        op = str(flt.get("op") or "equals").strip().lower()
        raw = _cell(row, fields, field)
        text = "" if raw is None else str(raw).strip()
        values = flt.get("values")
        if values is None:
            value = flt.get("value")
            values = [] if value is None else [value]
        values = [str(item).strip() for item in values]
        if op in ("equals", "in") and text not in values:
            return False
        if op in ("not_equals", "not_in") and text in values:
            return False
        if op == "contains" and not any(item in text for item in values):
            return False
        if op == "not_contains" and any(item in text for item in values):
            return False
    return True


def extract_bill_amount(rows: list, fields: list[str], config: dict) -> dict:
    """从金蝶单据查询（``ExecuteBillQuery``）行中按配置过滤并汇总金额。

    配置项（``measures`` 或某个组成项）:
    - ``amount_field``：金额字段，如采购入库单表头 ``FBillAllAmount_LC``；
      ``amount_terms`` 优先（多字段组合，如期末余额 = 借 - 贷）。
    - ``row_filters``：行过滤条件列表，每项 ``{field, op, value|values}``，
      ``op`` 支持 ``equals`` / ``not_equals`` / ``contains`` / ``not_contains`` / ``in`` / ``not_in``。
      空值（``None``）按空字符串参与比较，故 ``not_contains`` 会保留空值行。
    - ``dedupe_field``：按该字段去重后只计一次。单据查询按分录返回，
      表头金额字段在同单多条分录上会重复，必须按单号（如 ``FBillNo``）去重否则翻倍。

    返回结构与 :func:`extract_account_balance` 对齐：``total`` 合计值、
    ``departments``（单据口径无核算维度，恒为空）、``matched_rows`` 命中行数。
    """
    amount_field = str(config.get("amount_field") or "")
    amount_terms = config.get("amount_terms")
    terms: list[tuple[str, float]] = []
    if isinstance(amount_terms, list):
        for term in amount_terms:
            if isinstance(term, dict) and term.get("field"):
                terms.append((str(term["field"]), float(term.get("sign", 1))))
    if not terms and amount_field:
        terms = [(amount_field, 1.0)]
    filters = config.get("row_filters")
    dedupe_field = str(config.get("dedupe_field") or "").strip()

    total = 0.0
    matched_rows = 0
    seen: set[str] = set()
    for row in rows:
        if not _row_matches_filters(row, fields, filters):
            continue
        if dedupe_field:
            key = str(_cell(row, fields, dedupe_field) or "").strip()
            if key:
                if key in seen:
                    continue
                seen.add(key)
        amount = sum(sign * _parse_amount(_cell(row, fields, field)) for field, sign in terms)
        total += amount
        matched_rows += 1
    return {"total": round(total, 4), "departments": {}, "matched_rows": matched_rows}


# --------------------------------------------------------------------------- #
# 存货收发存汇总表取数执行器
# --------------------------------------------------------------------------- #
def extract_inventory_ledger(rows: list, fields: list[str], config: dict) -> dict:
    """从《存货收发存汇总表》行中汇总期末结存（金额或数量）。

    配置项（``measures``）:
    - ``amount_field``：汇总字段，默认 ``FENDAmount``（期末结存金额）；取数量口径时传 ``FENDQty``。
    - ``qty_field``：期末结存数量字段，默认 ``FENDQty``，随结果一并返回便于核对。
    - ``stock_field``：仓库字段，默认 ``FSTOCKId``（报表返回的是仓库名称）。
    - ``material_field``：物料编码字段，默认 ``FMATERIALBASEID``。
    - ``subtotal_suffix``：小计行物料编码后缀，默认 ``-总计``（如 ``BCP0000605-总计``）。

    该报表同一批结果里既有明细行也有小计行：小计行的仓库列为空、物料编码带 ``-总计``。
    汇总时必须跳过小计行，否则金额会被重复计算一倍（实测小计行金额 ≈ 明细行之和）。

    返回结构与 :func:`extract_account_balance` 对齐：``total`` 合计值、
    ``qty_total`` 期末结存数量合计、``departments``（本报表无维度，恒为空）、``matched_rows`` 命中明细行数。
    """
    amount_field = str(config.get("amount_field") or "FENDAmount")
    qty_field = str(config.get("qty_field") or "FENDQty")
    stock_field = str(config.get("stock_field") or "FSTOCKId")
    material_field = str(config.get("material_field") or "FMATERIALBASEID")
    subtotal_suffix = str(config.get("subtotal_suffix") or "-总计")

    total = 0.0
    qty_total = 0.0
    matched_rows = 0
    for row in rows:
        material = _text(_cell(row, fields, material_field))
        if subtotal_suffix and material.endswith(subtotal_suffix):
            continue
        # 小计/合计行没有仓库，跳过避免与明细重复计入
        if not _text(_cell(row, fields, stock_field)):
            continue
        total += _parse_amount(_cell(row, fields, amount_field))
        qty_total += _parse_amount(_cell(row, fields, qty_field))
        matched_rows += 1
    return {
        "total": round(total, 4),
        "qty_total": round(qty_total, 4),
        "departments": {},
        "matched_rows": matched_rows,
    }


# --------------------------------------------------------------------------- #
# 零售出库（聚水潭）取数执行器
# --------------------------------------------------------------------------- #
def extract_sales_outbound(rows: list, config: dict) -> dict:
    """从聚水潭销售出库单中汇总「零售出库未税总金额」。

    配置项（``measures``）:
    - ``amount_source``：取数口径，``order.pay_amount``（应付金额，默认）/
      ``order.paid_amount``（支付金额）/ ``order.buyer_paid_amount`` /
      ``order.seller_income_amount`` / ``items.sale_amount``（明细金额合计）。
    - ``tax_rate``：税率（百分比），未税金额 = 含税金额 / (1 + tax_rate/100)；为 0 时等于含税金额。
    - ``tax_inclusive``：接口金额是否含税，默认 True。
    - ``by_shop``：是否按店铺拆分（店铺作为核算维度写入 ``metric_value``）。

    返回结构与 :func:`extract_account_balance` 对齐：``total``（未税金额）、
    ``departments``（按店铺）、``matched_rows``（单据数）。
    """
    amount_source = str(config.get("amount_source") or "items.auto")
    tax_rate = float(config.get("tax_rate") or 0)
    tax_inclusive = bool(config.get("tax_inclusive", True))
    by_shop = bool(config.get("by_shop"))
    auto_fields = config.get("auto_fields")
    summary = summarize_outbound_amount(
        [row for row in rows if isinstance(row, dict)],
        amount_source=amount_source,
        tax_rate=tax_rate,
        tax_inclusive=tax_inclusive,
        by_shop=by_shop,
        auto_fields=auto_fields,
    )
    departments: dict[str, dict[str, Any]] = {}
    for shop_key, bucket in (summary.get("by_shop") or {}).items():
        departments[shop_key] = {
            "name": str(bucket.get("shop_name") or shop_key or "未指定店铺"),
            "value": float(bucket.get("untaxed_amount") or 0),
            "rows": int(bucket.get("order_count") or 0),
        }
    return {
        "total": float(summary["untaxed_amount"]),
        "tax_inclusive_amount": float(summary["tax_inclusive_amount"]),
        "order_count": int(summary["order_count"]),
        "item_qty": float(summary["item_qty"]),
        "departments": departments,
        "matched_rows": int(summary["order_count"]),
    }


# --------------------------------------------------------------------------- #
# 单值接口（CRM 订单未税金额）取数执行器
# --------------------------------------------------------------------------- #
def _dig(payload: Any, path: str) -> Any:
    """按点号路径取值，如 ``data`` / ``data.amount``；任一层缺失返回 ``None``。"""
    current: Any = payload
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def extract_api_scalar(payload: dict, config: dict) -> dict:
    """从外部接口响应中取单个数值或两个数值的比率（如 CRM 订单/报价指标）。

    配置项（``measures``）:
    - ``data_field``：数值所在字段路径，默认 ``data``（支持 ``data.amount`` 这类点号路径）。
    - ``value_scale``：单值分支的取值倍数，默认 1；接口返回正数的指标要取负数时传 -1
      （如 CRM 退货/退款金额，本系统按负数口径入账）。
    - ``numerator_field`` / ``denominator_field``：配置后按比率取值（分子 ÷ 分母），
      用于「报价成功率」这类需要两个计数的指标；分母为 0 时取 0，避免除零。
    - ``ratio_scale``：比率放大倍数，默认 1；比率类指标传 100 即输出百分数。

    返回结构与 :func:`extract_account_balance` 对齐：``total`` 合计值、
    ``departments``（单值接口无维度，恒为空）、``matched_rows`` 命中标记。
    """
    data_field = str(config.get("data_field") or "data")
    numerator_field = config.get("numerator_field")
    if numerator_field:
        numerator = _parse_amount(_dig(payload, str(numerator_field)))
        denominator = _parse_amount(_dig(payload, str(config.get("denominator_field") or data_field)))
        scale = float(config.get("ratio_scale") or 1)
        total = (numerator / denominator * scale) if denominator else 0.0
        return {"total": round(total, 4), "departments": {}, "matched_rows": 0 if not denominator else 1}
    raw = _dig(payload, data_field)
    value_scale = float(config.get("value_scale") or 1)
    return {
        "total": round(_parse_amount(raw) * value_scale, 4),
        "departments": {},
        "matched_rows": 0 if raw is None else 1,
    }


# --------------------------------------------------------------------------- #
# 取数辅助
# --------------------------------------------------------------------------- #
def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _amount_terms(config: dict) -> list[tuple[str, float]]:
    """金额取值项：``amount_terms`` 优先（多字段加权，如未税 = 应收 − 税金），退回 ``amount_field``。"""
    terms: list[tuple[str, float]] = []
    raw_terms = config.get("amount_terms")
    if isinstance(raw_terms, list):
        for term in raw_terms:
            if isinstance(term, dict) and term.get("field"):
                terms.append((str(term["field"]), float(term.get("sign", 1))))
    if not terms:
        amount_field = str(config.get("amount_field") or "")
        if amount_field:
            terms = [(amount_field, 1.0)]
    return terms


def _row_status_allowed(row: Any, fields: list[str], config: dict) -> bool:
    """按 ``status_field`` / ``status_allow`` 过滤行（``status_allow`` 为空 = 不过滤）。"""
    raw_allow = config.get("status_allow", ["384"])
    if raw_allow is None:
        return True
    allowed = {_text(item) for item in (raw_allow if isinstance(raw_allow, list) else [raw_allow]) if _text(item)}
    if not allowed:
        return True
    status_field = str(config.get("status_field") or "status")
    return _text(_cell(row, fields, status_field)) in allowed


# --------------------------------------------------------------------------- #
# 业务员维度取数执行器（CRM 订单 / 发货明细）
# --------------------------------------------------------------------------- #
def extract_person_amount(rows: list, fields: list[str], config: dict) -> dict:
    """把 CRM 订单明细按业务员（下单人）分组汇总金额。

    配置项（``measures`` 或 component）:
    - ``person_field``：业务员字段，默认 ``create_id``（订单下单人）。
    - ``amount_terms`` / ``amount_field``：金额取值项。
    - ``value_mode``：``amount``（默认，金额合计）/ ``count_orders``（订单数）/ ``count_customers``
      （``customer_field`` 指定的客户去重数，默认 ``customer``）。
    - ``exclude_empty_person``：为真时丢弃没有业务员（``person_field`` 为空）的行，
      如客户表中「未分配业务员」的客户不计入任何业务员。
    - ``status_field`` / ``status_allow``：有效状态过滤，默认 ``status`` ∈ ``["384"]``（剔除作废 522）。
    - ``row_filters``：行过滤条件（``[{field, op, value|values}]``，见 :func:`_row_matches_filters`），
      用于订单类型（``order_type=1/2``）或新老客户（``is_new=1/2``）等口径拆分。
    - ``omit_zero_persons``：为真（默认）时丢弃合计为 0 的业务员，只保留有业绩的人。

    返回 ``{"persons": {业务员ID: {"value": 金额, "rows": 行数}}, "total": 合计, "matched_rows": 命中行数}``。
    """
    person_field = str(config.get("person_field") or "create_id")
    terms = _amount_terms(config)
    value_mode = str(config.get("value_mode") or "amount")
    customer_field = str(config.get("customer_field") or "customer")
    exclude_empty_person = bool(config.get("exclude_empty_person"))
    omit_zero = bool(config.get("omit_zero_persons", True))
    persons: dict[str, dict] = {}
    matched_rows = 0
    for row in rows:
        if not _row_status_allowed(row, fields, config):
            continue
        if not _row_matches_filters(row, fields, config.get("row_filters")):
            continue
        person = _text(_cell(row, fields, person_field))
        if exclude_empty_person and not person:
            continue
        matched_rows += 1
        amount = sum(sign * _parse_amount(_cell(row, fields, field)) for field, sign in terms)
        bucket = persons.setdefault(person, {"value": 0.0, "rows": 0})
        bucket["value"] = round(float(bucket["value"]) + amount, 4)
        bucket["rows"] = int(bucket["rows"]) + 1
        if value_mode == "count_customers":
            # 客户去重：内贸/外贸可能同一客户重复下单，按客户ID去重后再计数
            customer = _text(_cell(row, fields, customer_field))
            bucket.setdefault("customers", set()).add(customer or f"__row_{matched_rows}")
    if value_mode == "count_orders":
        persons = {
            key: {"value": float(bucket["rows"]), "rows": bucket["rows"]}
            for key, bucket in persons.items()
        }
    elif value_mode == "count_customers":
        persons = {
            key: {"value": float(len(bucket.get("customers") or ())), "rows": bucket["rows"],
                  "customers": bucket.get("customers") or set()}
            for key, bucket in persons.items()
        }
    if omit_zero:
        persons = {key: bucket for key, bucket in persons.items() if round(float(bucket["value"]), 4) != 0}
    total = round(sum(float(bucket["value"]) for bucket in persons.values()), 4)
    return {"persons": persons, "total": total, "matched_rows": matched_rows}


def build_order_amount_index(rows: list, fields: list[str], config: dict) -> dict[str, dict]:
    """把订单明细整理成 ``{订单号: {person, unit_price, amount, qty}}``，供发货明细关联。

    未税单价 = 订单未税金额 ÷ 订单数量（数量为 0 时按 0 处理），
    这样发货明细可以用「发货数量 × 未税单价」直接结转未税收入。
    """
    number_field = str(config.get("order_number_field") or "number")
    person_field = str(config.get("person_field") or "create_id")
    qty_field = str(config.get("order_qty_field") or "qty")
    terms = _amount_terms(config)
    index: dict[str, dict] = {}
    for row in rows:
        if not _row_status_allowed(row, fields, config):
            continue
        if not _row_matches_filters(row, fields, config.get("row_filters")):
            continue
        number = _text(_cell(row, fields, number_field))
        if not number or number in index:
            continue
        qty = _parse_amount(_cell(row, fields, qty_field))
        amount = sum(sign * _parse_amount(_cell(row, fields, field)) for field, sign in terms)
        index[number] = {
            "person": _text(_cell(row, fields, person_field)),
            "unit_price": (amount / qty) if qty else 0.0,
            "amount": amount,
            "qty": qty,
        }
    return index


def extract_shipment_person_amount(
    shipment_rows: list, order_index: dict[str, dict], config: dict
) -> dict:
    """按发货明细汇总「业务员 × 出货」。

    发货接口只给「CRM单号 / 发货数量 / 订单单价 / 订单数量」，不含业务员与未税金额，
    所以必须先按订单号关联订单明细（``order_index``）拿业务员与未税单价。
    关联不到的订单号计入 ``missing_rows``（订单创建月早于回看窗口时会出现）。

    ``value_mode`` 控制取值口径：
    - ``amount``（默认）：金额 = Σ(发货数量 × 该订单未税单价)；
    - ``qty``：数量 = Σ发货数量。
    """
    number_field = str(config.get("shipment_number_field") or "order_number")
    qty_field = str(config.get("shipment_qty_field") or "send_qty")
    value_mode = str(config.get("value_mode") or "amount")
    omit_zero = bool(config.get("omit_zero_persons", True))
    persons: dict[str, dict] = {}
    matched_rows = 0
    missing_rows = 0
    missing_orders: set[str] = set()
    for row in shipment_rows:
        number = _text(_cell(row, [], number_field))
        info = order_index.get(number)
        if info is None:
            missing_rows += 1
            if number:
                missing_orders.add(number)
            continue
        matched_rows += 1
        qty = _parse_amount(_cell(row, [], qty_field))
        if value_mode == "qty":
            amount = round(qty, 4)
        else:
            amount = round(qty * float(info.get("unit_price") or 0), 4)
        person = str(info.get("person") or "")
        bucket = persons.setdefault(person, {"value": 0.0, "rows": 0})
        bucket["value"] = round(float(bucket["value"]) + amount, 4)
        bucket["rows"] = int(bucket["rows"]) + 1
    if omit_zero:
        persons = {key: bucket for key, bucket in persons.items() if round(float(bucket["value"]), 4) != 0}
    return {
        "persons": persons,
        "total": round(sum(float(bucket["value"]) for bucket in persons.values()), 4),
        "matched_rows": matched_rows,
        "missing_rows": missing_rows,
        "missing_orders": sorted(missing_orders)[:20],
    }


def extract_quote_person_stat(rows: list, fields: list[str], config: dict) -> dict:
    """把 CRM 报价单明细按业务员汇总「次数 / 已转单数 / 报价未税 / 料工费」四个计数。

    各统计口径由调用方（``stat``）决定怎么算，这里只负责按业务员累加原始计数：
    - ``count``：报价次数（报价单条数，接口已按 status='E' 已审核 + 报价月过滤）；
    - ``success_rate``：报价成功率 = 已转订单数 ÷ 报价次数 ×100%；
    - ``gross_profit_rate``：报价毛利率 =（报价未税 − 料工费）÷ 报价未税 ×100%。

    配置项（``measures`` 或 component）:
    - ``person_field``：业务员字段，默认 ``create_id``。
    - ``amount_field``：报价未税总价字段，默认 ``not_tax_all_quote_amount``。
    - ``cost_field``：料工费字段，默认 ``material_labor_cost``。
    - ``transformation_field`` / ``transformation_allow``：是否转订单标识，默认
      ``transformation`` ∈ ``["1"]``（已转订单）。
    """
    person_field = str(config.get("person_field") or "create_id")
    amount_field = str(config.get("amount_field") or "not_tax_all_quote_amount")
    cost_field = str(config.get("cost_field") or "material_labor_cost")
    transformation_field = str(config.get("transformation_field") or "transformation")
    raw_allow = config.get("transformation_allow", ["1"])
    transformed_values = {
        _text(item) for item in (raw_allow if isinstance(raw_allow, list) else [raw_allow]) if _text(item)
    }
    persons: dict[str, dict] = {}
    for row in rows:
        person = _text(_cell(row, fields, person_field))
        if not person:
            continue
        bucket = persons.setdefault(person, {"count": 0.0, "transformed": 0.0, "amount": 0.0, "cost": 0.0})
        bucket["count"] += 1
        if _text(_cell(row, fields, transformation_field)) in transformed_values:
            bucket["transformed"] += 1
        bucket["amount"] = round(bucket["amount"] + _parse_amount(_cell(row, fields, amount_field)), 4)
        bucket["cost"] = round(bucket["cost"] + _parse_amount(_cell(row, fields, cost_field)), 4)
    return {"persons": persons, "matched_rows": int(sum(item["count"] for item in persons.values()))}


def _quote_person_value(stat: str, bucket: dict) -> float:
    """按 ``stat`` 把报价计数换算成指标值。"""
    count = float(bucket.get("count") or 0)
    if stat == "success_rate":
        return round(float(bucket.get("transformed") or 0) / count * 100, 4) if count else 0.0
    if stat == "gross_profit_rate":
        amount = float(bucket.get("amount") or 0)
        return round((amount - float(bucket.get("cost") or 0)) / amount * 100, 4) if amount else 0.0
    return round(count, 4)


def _parse_datetime_value(value: Any) -> datetime | None:
    """解析 CRM 时间字段：``2026-09-08 09:46:53`` / ISO 串 / Unix 秒时间戳（``createtime``）。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text))
        except (OverflowError, OSError, ValueError):
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _datetime_in_period(moment: datetime | None, period_type: str, period: str) -> bool:
    """时间点是否落在期间内（月 ``2026-09`` / 日 ``2026-09-28`` / 年 ``2026``）。"""
    if moment is None:
        return False
    if period_type == "day":
        return moment.strftime("%Y-%m-%d") == period
    if period_type == "year":
        return moment.strftime("%Y") == period
    return moment.strftime("%Y-%m") == period


def extract_push_person_stat(
    rows: list, fields: list[str], config: dict, period_type: str, period: str
) -> dict:
    """按「ERP 下推时间」落在当期过滤订单，按业务员汇总下推金额或平均下推周期。

    配置项（``measures`` 或 component）:
    - ``push_status_field`` / ``push_status_allow``：下推状态，默认 ``erp_push_status`` ∈ ``["1"]``（已下推）。
    - ``push_date_field``：下推时间字段，默认 ``erp_push_date``。
    - ``cycle_start_field``：建单时间字段，默认 ``createtime``（Unix 秒）。
    - ``amount_terms`` / ``amount_field``：下推金额取值项。
    - ``stat``：``amount`` = 下推金额合计；``period_days`` = 下推周期（天）
      = Σ(下推时间 − 建单时间) ÷ 下推订单数（按订单数加权，非按金额）。

    返回 ``persons`` 为 ``{业务员ID: {"value": 指标值, "orders": 下推订单数, "days": 天数合计}}``。
    """
    push_status_field = str(config.get("push_status_field") or "erp_push_status")
    raw_allow = config.get("push_status_allow", ["1"])
    allowed = {_text(item) for item in (raw_allow if isinstance(raw_allow, list) else [raw_allow]) if _text(item)}
    push_date_field = str(config.get("push_date_field") or "erp_push_date")
    cycle_start_field = str(config.get("cycle_start_field") or "createtime")
    person_field = str(config.get("person_field") or "create_id")
    stat = str(config.get("stat") or "amount")
    terms = _amount_terms(config)
    persons: dict[str, dict] = {}
    matched_rows = 0
    cycle_rows = 0
    for row in rows:
        if not _row_status_allowed(row, fields, config):
            continue
        if not _row_matches_filters(row, fields, config.get("row_filters")):
            continue
        if allowed and _text(_cell(row, fields, push_status_field)) not in allowed:
            continue
        push_at = _parse_datetime_value(_cell(row, fields, push_date_field))
        if not _datetime_in_period(push_at, period_type, period):
            continue
        matched_rows += 1
        amount = sum(sign * _parse_amount(_cell(row, fields, field)) for field, sign in terms)
        started = _parse_datetime_value(_cell(row, fields, cycle_start_field))
        days = 0.0
        if started is not None and push_at is not None:
            days = max((push_at - started).total_seconds() / 86400.0, 0.0)
            cycle_rows += 1
        person = _text(_cell(row, fields, person_field))
        bucket = persons.setdefault(person, {"amount": 0.0, "days": 0.0, "orders": 0})
        bucket["amount"] = round(float(bucket["amount"]) + amount, 4)
        bucket["days"] = round(float(bucket["days"]) + days, 4)
        bucket["orders"] = int(bucket["orders"]) + 1
    result: dict[str, dict] = {}
    for person, bucket in persons.items():
        if stat == "period_days":
            orders = int(bucket["orders"])
            value = round(float(bucket["days"]) / orders, 4) if orders else 0.0
        else:
            value = round(float(bucket["amount"]), 4)
        if config.get("omit_zero_persons", True) and value == 0:
            continue
        result[person] = {"value": value, "orders": int(bucket["orders"]), "days": round(float(bucket["days"]), 4)}
    return {
        "persons": result,
        "total": round(sum(float(bucket["value"]) for bucket in result.values()), 4),
        "matched_rows": matched_rows,
        "cycle_rows": cycle_rows,
    }


# --------------------------------------------------------------------------- #
# 应收款账龄计提（金蝶《应收款账龄分析表》）取数执行器
# --------------------------------------------------------------------------- #
def period_end_date(period_type: str, period_value: str) -> date:
    """期间末日（月指标 → 当月最后一天；日指标 → 当天；年指标 → 12-31）。"""
    text = str(period_value)
    if period_type == "day":
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    if period_type == "year":
        return date(int(text[:4]), 12, 31)
    year, month = (int(part) for part in text[:7].split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


def _parse_date(value: Any) -> date | None:
    """金蝶日期字段是 ``2026-04-10`` 或 ``2026-04-10T00:00:00`` 两种写法。"""
    text = _text(value)[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def aging_buckets(config: dict) -> list[tuple[int | None, float]]:
    """账龄区间配置 → ``[(max_days, rate)]``，``max_days`` 为空表示兜底档。"""
    raw = config.get("buckets") or DEFAULT_AGING_BUCKETS
    buckets: list[tuple[int | None, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        max_days = item.get("max_days")
        buckets.append(
            (int(max_days) if max_days not in (None, "") else None, float(item.get("rate") or 0))
        )
    return buckets or [(None, 0.0)]


def aging_rate(days: int, buckets: list[tuple[int | None, float]]) -> float:
    """按账龄天数取计提比例（第一个满足 ``days <= max_days`` 的档位）。"""
    for max_days, rate in buckets:
        if max_days is None or days <= max_days:
            return rate
    return buckets[-1][1]


def aging_bucket_label(index: int, buckets: list[tuple[int | None, float]]) -> str:
    """区间标签：``0-30`` / ``31-60`` / ... / ``>365``。"""
    max_days = buckets[index][0]
    previous = buckets[index - 1][0] if index else None
    if max_days is None:
        return f">{previous}" if previous is not None else "全部"
    return f"{0 if previous is None else previous + 1}-{max_days}"


def extract_ar_aging_provision(rows: list, fields: list[str], config: dict, as_of: date) -> dict:
    """按账龄区间对「尚未收款金额」计提坏账，返回合计与按客户明细。

    来源是金蝶《应收款账龄分析表》按单据显示（``FByBill=true``）的返回：
    每张单据一行，客户块末尾还有一行 ``xxx(小计)``（单据编号为空，必须跳过）。

    配置项（``measures``）:
    - ``netting``：计提口径。``customer``（默认）= 先按往来单位汇总净值，
      **客户净额 ≤ 0 的不纳入计提**（应收与预收相抵后没有可计提余额），净额为正的客户
      再按各账龄档的净额乘比例；``bill`` = 逐单计提（不做客户层净额过滤）。
    - ``amount_field``：尚未收款金额字段，默认 ``FBalanceAmt``（本位币；原币为 ``FBalanceAmtFor``）。
    - ``customer_code_field`` / ``customer_name_field``：往来单位编码与名称字段。
    - ``bill_no_field``：单据编号字段，用于识别并跳过「小计」行。
    - ``date_field`` / ``fallback_date_field``：账龄基准字段（默认到期日 ``FEndDate``，
      缺失时退化为业务日期 ``FDate``）。
    - ``buckets``：``[{"max_days": 30, "rate": 0}, ..., {"max_days": None, "rate": 1}]``。
    - ``detail_code_exclude_in``：往来单位编码命中即排除（如剔除编码 100-113 的内部客户）。
    - ``skip_negative_amount``：仅 ``netting = bill`` 时生效，为真时只对正数单据计提。

    返回结构与 :func:`extract_account_balance` 对齐：``total`` 计提金额、
    ``departments``（按客户，值为该客户计提金额）、``matched_rows``；另附
    ``amount_total``（计提基数合计 = 纳入计提客户的净额之和）、``buckets``（各档金额/计提明细）、
    ``excluded_customers``（净额为负被排除的客户数）。
    """
    amount_field = str(config.get("amount_field") or "FBalanceAmt")
    customer_code_field = str(config.get("customer_code_field") or "FContactUnitNumber")
    customer_name_field = str(config.get("customer_name_field") or "FCONTACTUNIT")
    bill_no_field = str(config.get("bill_no_field") or "FBillNo")
    date_field = str(config.get("date_field") or "FEndDate")
    fallback_date_field = str(config.get("fallback_date_field") or date_field)
    netting = str(config.get("netting") or "customer").strip().lower()
    buckets = aging_buckets(config)
    labels = [aging_bucket_label(index, buckets) for index in range(len(buckets))]

    code_exclude = config.get("detail_code_exclude_in") or []
    if isinstance(code_exclude, str):
        code_exclude = [code_exclude]
    code_exclude = {str(item).strip() for item in code_exclude if str(item).strip()}
    skip_negative = bool(config.get("skip_negative_amount"))

    # 先逐行解析出「客户 + 账龄档 + 金额」，再按口径汇总
    entries: list[tuple[str, str, int, float]] = []
    missing_date = 0
    for row in rows:
        # 「小计」行没有单据编号，金额是该客户合计，计入会重复
        if not _text(_cell(row, fields, bill_no_field)):
            continue
        code = _text(_cell(row, fields, customer_code_field))
        if code_exclude and code in code_exclude:
            continue
        base_date = _parse_date(_cell(row, fields, date_field)) or _parse_date(
            _cell(row, fields, fallback_date_field)
        )
        if base_date is None:
            missing_date += 1
            continue
        amount = _parse_amount(_cell(row, fields, amount_field))
        days = (as_of - base_date).days
        index = next(
            (i for i, (max_days, _) in enumerate(buckets) if max_days is None or days <= max_days),
            len(buckets) - 1,
        )
        name = _text(_cell(row, fields, customer_name_field)) or code
        entries.append((code or name, name, index, amount))

    total = 0.0
    amount_total = 0.0
    matched_rows = 0
    skipped_negative = 0
    excluded_customers = 0
    departments: dict[str, dict[str, Any]] = {}
    bucket_stats: dict[str, dict[str, Any]] = {
        label: {"amount": 0.0, "provision": 0.0, "rows": 0} for label in labels
    }

    if netting == "customer":
        # 按客户汇总各档净额 → 客户净额 ≤ 0 整体不计提，正数客户按档位净额计提
        grouped: dict[str, dict[str, Any]] = {}
        for code, name, index, amount in entries:
            item = grouped.setdefault(code, {"name": name, "amounts": [0.0] * len(buckets), "rows": 0})
            item["amounts"][index] = round(float(item["amounts"][index]) + amount, 4)
            item["rows"] = int(item["rows"]) + 1
        for code, item in grouped.items():
            net_amount = round(sum(item["amounts"]), 4)
            if net_amount <= 0:
                excluded_customers += 1
                continue
            provision = round(
                sum(item["amounts"][i] * buckets[i][1] for i in range(len(buckets))), 4
            )
            total += provision
            amount_total += net_amount
            matched_rows += int(item["rows"])
            departments[code] = {"name": item["name"], "value": provision, "rows": int(item["rows"])}
            for index, label in enumerate(labels):
                bucket_amount = item["amounts"][index]
                if not bucket_amount:
                    continue
                stat = bucket_stats[label]
                stat["amount"] = round(float(stat["amount"]) + bucket_amount, 4)
                stat["provision"] = round(
                    float(stat["provision"]) + bucket_amount * buckets[index][1], 4
                )
                stat["rows"] = int(stat["rows"]) + 1
    else:
        for code, name, index, amount in entries:
            if skip_negative and amount <= 0:
                skipped_negative += 1
                continue
            provision = amount * buckets[index][1]
            total += provision
            amount_total += amount
            matched_rows += 1
            label = labels[index]
            stat = bucket_stats[label]
            stat["amount"] = round(float(stat["amount"]) + amount, 4)
            stat["provision"] = round(float(stat["provision"]) + provision, 4)
            stat["rows"] = int(stat["rows"]) + 1
            bucket = departments.setdefault(code, {"name": name, "value": 0.0, "rows": 0})
            bucket["value"] = round(float(bucket["value"]) + provision, 4)
            bucket["rows"] = int(bucket["rows"]) + 1
    return {
        "total": round(total, 4),
        "amount_total": round(amount_total, 4),
        "departments": departments,
        "matched_rows": matched_rows,
        "missing_date": missing_date,
        "skipped_negative": skipped_negative,
        "excluded_customers": excluded_customers,
        "netting": netting,
        "buckets": bucket_stats,
        "as_of": as_of.isoformat(),
    }


def _demand_prefixes(config: dict) -> list[str]:
    raw = config.get("demand_prefixes") or config.get("demand_prefix") or "BH"
    if isinstance(raw, str):
        raw = [item for item in raw.replace(",", " ").split() if item.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


def select_demand_rows(rows: list, fields: list[str], config: dict) -> list[dict]:
    """筛出「需求单据以指定前缀开头」的生产入库单行（如备货订单 ``BH``）。"""
    demand_field = str(config.get("demand_field") or "FReqBillNo")
    prefixes = _demand_prefixes(config)
    if not prefixes:
        return [row for row in rows if isinstance(row, dict)]
    picked: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        demand = _text(_cell(row, fields, demand_field))
        if demand and any(demand.startswith(prefix) for prefix in prefixes):
            picked.append(row)
    return picked


def production_order_numbers(rows: list, fields: list[str], config: dict) -> set[str]:
    """从（已按需求单据过滤的）生产入库单行里取生产订单号集合。"""
    order_field = str(config.get("order_field") or "FMoBillNo")
    return {_text(_cell(row, fields, order_field)) for row in rows if _text(_cell(row, fields, order_field))}


def extract_production_instock(
    rows: list, fields: list[str], config: dict, order_facts: dict[str, dict]
) -> dict:
    """按「需求单据前缀 + 生产订单口径」汇总生产入库单对应的生产订单金额。

    配置项（``measures``）:
    - ``demand_field`` / ``demand_prefix``（或 ``demand_prefixes``）：需求单据字段与要求的前缀，
      默认 ``FReqBillNo`` + ``BH``（备货订单）。
    - ``order_field``：生产入库单上的生产订单号字段，默认 ``FMoBillNo``。
    - ``order_amount_field``：生产订单单据头的金额字段，默认 ``F_UIVG_Decimal_83g``（Y订单金额）。
    - ``order_qty_field`` / ``inbound_qty_field``：生产订单数量字段（默认 ``FQty``）与
      生产入库实收数量字段（默认 ``FRealQty``），用于非 ``C.`` 订单按单价结转。
    - ``dedupe_material_keyword``：生产订单物料编码含该关键字（默认 ``C.``，即半成品订单）时，
      同一生产订单当月多次入库**只计一次**单据头金额。

    结算口径（``order_facts`` 为「生产订单号 → 单据头金额/物料/生产数量」，
    由 :func:`fetch_production_order_facts` 取回）:

    - 生产订单物料含 ``C.``（半成品订单）：当月入库只计**一次整单金额**
      （一张 ``C.`` 订单会有多个成品分录/多次入库，按行相加会成倍放大）；
    - 其他订单（如 ``BCP`` 成品、分多次入库）：按**单价**结转，
      单价 = 单据头金额 ÷ 生产数量，金额 = Σ(该订单本期入库数量 × 单价)；
      生产数量为 0/缺失时无法算单价，退化为整单金额计一次并计入 ``fallback_orders``。

    返回结构与 :func:`extract_account_balance` 对齐：``total`` 去重后合计金额、
    ``departments``（按需求单据即备货订单号拆分，作核算维度）、``matched_rows``（生产订单数）。
    """
    picked = select_demand_rows(rows, fields, config)
    order_field = str(config.get("order_field") or "FMoBillNo")
    demand_field = str(config.get("demand_field") or "FReqBillNo")
    inbound_qty_field = str(config.get("inbound_qty_field") or "FRealQty")
    dedupe_keyword = _text(config.get("dedupe_material_keyword") or "C.")

    demand_orders: dict[str, set[str]] = {}
    order_inbound_qty: dict[str, float] = {}
    for row in picked:
        order_no = _text(_cell(row, fields, order_field))
        demand = _text(_cell(row, fields, demand_field))
        if not order_no:
            continue
        demand_orders.setdefault(demand, set()).add(order_no)
        order_inbound_qty[order_no] = order_inbound_qty.get(order_no, 0.0) + _parse_amount(
            _cell(row, fields, inbound_qty_field)
        )

    order_value: dict[str, float] = {}
    deduped_orders: list[str] = []
    fallback_orders: list[str] = []
    for order_no, inbound_qty in order_inbound_qty.items():
        fact = order_facts.get(order_no) or {}
        amount = _parse_amount(fact.get("amount"))
        material = _text(fact.get("material"))
        if dedupe_keyword and dedupe_keyword in material:
            # 半成品（C.）生产订单：当月只计一次整单金额
            order_value[order_no] = round(amount, 4)
            deduped_orders.append(order_no)
            continue
        order_qty = _parse_amount(fact.get("qty"))
        if order_qty:
            unit_price = amount / order_qty
            order_value[order_no] = round(unit_price * inbound_qty, 4)
        else:
            order_value[order_no] = round(amount, 4)
            fallback_orders.append(order_no)

    departments: dict[str, dict[str, Any]] = {}
    for demand, orders in demand_orders.items():
        value = round(sum(order_value.get(order_no, 0.0) for order_no in orders), 4)
        departments[demand] = {"name": demand or "未指定需求单据", "value": value, "rows": len(orders)}

    missing = [order_no for order_no in order_value if order_no not in order_facts]
    return {
        "total": round(sum(order_value.values()), 4),
        "departments": departments,
        "matched_rows": len(order_value),
        "inbound_rows": len(picked),
        "order_count": len(order_value),
        "deduped_orders": len(deduped_orders),
        "fallback_orders": len(fallback_orders),
        "missing_orders": missing,
    }


async def fetch_production_order_facts(
    connection_id: int | None, order_numbers: list[str], config: dict, chunk_size: int = 50
) -> tuple[dict[str, dict], int]:
    """按生产订单号批量取生产订单（``PRD_MO``）单据头的金额、物料与生产数量。

    生产订单号来自生产入库单行，无法在静态请求模板里写死，因此这里按需实时回查
    金蝶单据查询接口（只读）。返回 ``({生产订单号: {"amount", "material", "qty"}}, 未取到的订单数)``；
    ``material`` 是该订单全部分录的物料编码（含 ``C.`` 即按半成品订单口径处理），
    ``qty`` 是全部分录生产数量之和。
    """
    if not order_numbers:
        return {}, 0
    if not connection_id:
        raise ValueError("生产入库指标缺少金蝶连接配置，无法回查生产订单")

    order_form_id = str(config.get("order_form_id") or "PRD_MO")
    number_field = str(config.get("order_number_field") or "FBillNo")
    amount_field = str(config.get("order_amount_field") or "F_UIVG_Decimal_83g")
    material_field = str(config.get("order_material_field") or "FMaterialId.FNumber")
    qty_field = str(config.get("order_qty_field") or "FQty")
    status_filter = str(config.get("order_status_filter") or "").strip()

    async with async_db_session() as db:
        connection = await db.get(KingdeeConnectionModel, connection_id)
    if connection is None:
        raise ValueError(f"金蝶连接配置不存在: {connection_id}")
    client = KingdeeService._client_from(connection)

    facts: dict[str, dict] = {}
    for start in range(0, len(order_numbers), chunk_size):
        chunk = order_numbers[start : start + chunk_size]
        condition = " or ".join(f"{number_field}='{number_no}'" for number_no in chunk)
        filter_string = f"({condition})"
        if status_filter:
            filter_string = f"{filter_string} and {status_filter}"
        _, items = await client.bill_query(
            KingdeeBillQueryRequest(
                form_id=order_form_id,
                field_keys=f"{number_field},{amount_field},{material_field},{qty_field}",
                filter_string=filter_string,
                limit=len(chunk) * 50,
            )
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            number_no = _text(item.get(number_field))
            if not number_no:
                continue
            fact = facts.setdefault(number_no, {"amount": None, "materials": [], "qty": 0.0})
            if fact["amount"] is None:
                # 单据头金额按分录重复返回，取第一次出现的值
                fact["amount"] = _parse_amount(item.get(amount_field))
            material = _text(item.get(material_field))
            if material and material not in fact["materials"]:
                fact["materials"].append(material)
            # 生产数量是分录字段，多分录订单求和
            fact["qty"] = round(float(fact["qty"]) + _parse_amount(item.get(qty_field)), 4)
    for fact in facts.values():
        fact["amount"] = round(_parse_amount(fact["amount"]), 4)
        fact["material"] = " ".join(fact["materials"])
    missing = [order_no for order_no in order_numbers if order_no not in facts]
    if missing:
        logger.warning(
            f"生产入库指标回查生产订单缺失 {len(missing)} 张（按 0 计入）: {missing[:10]}"
        )
    return facts, len(missing)


async def _resolve_org_id(db, org_code: str | None) -> int | None:
    if not org_code:
        return None
    return (
        await db.execute(select(MasterOrgModel.id).where(MasterOrgModel.code == str(org_code)))
    ).scalars().first()


async def _resolve_dept_id(db, org_id: int | None, dept_code: str) -> int | None:
    if org_id is None or not dept_code:
        return None
    return (
        await db.execute(
            select(MasterDeptModel.id).where(MasterDeptModel.org_id == org_id, MasterDeptModel.code == dept_code)
        )
    ).scalars().first()


async def _load_person_index(db) -> dict[str, dict]:
    """CRM 业务员ID（订单 ``create_id``）→ 标准人员信息。

    解析链：``create_id`` → ``source_person``（``source_type='crm'``，取 ``raw_json.id`` 命中）
    → 工号（``raw_json.number``）→ ``master_person.code`` 得到标准人员；
    标准人员匹配不到时只保留 CRM 侧的编码/姓名，业务员行照旧输出、不丢数。
    """
    masters = {
        _text(code): (int(pid), _text(name))
        for pid, code, name in (
            await db.execute(select(MasterPersonModel.id, MasterPersonModel.code, MasterPersonModel.name))
        ).all()
    }
    rows = (
        await db.execute(
            select(
                SourcePersonModel.source_code,
                SourcePersonModel.source_name,
                SourcePersonModel.raw_json,
            ).where(SourcePersonModel.source_type == CRM_SOURCE_TYPE)
        )
    ).all()
    index: dict[str, dict] = {}
    for source_code, source_name, raw in rows:
        raw = raw if isinstance(raw, dict) else {}
        crm_id = raw.get("id")
        if crm_id is None:
            continue
        person_id, master_name = masters.get(_text(raw.get("number")), (None, ""))
        index[str(crm_id)] = {
            "person_id": person_id,
            "person_code": _text(source_code) or f"CRM{crm_id}",
            "person_name": _text(source_name) or master_name or f"CRM{crm_id}",
        }
    return index


async def _latest_success_run(db, job_id: int, period_value: str | None = None) -> MetaSyncRunModel | None:
    """取该任务在指定期间最近一次成功的同步批次（期间为空则取最近一次）。

    先只查主键再取整行：``rows_json`` 是几万行的原始返回，跟着一起排序会撑爆
    MySQL 的 sort buffer（Out of sort memory）。
    """
    conditions = [MetaSyncRunModel.job_id == job_id, MetaSyncRunModel.status == "success"]
    if period_value:
        conditions.append(MetaSyncRunModel.period_value == period_value)
    run_id = (
        await db.execute(
            select(MetaSyncRunModel.id).where(*conditions).order_by(MetaSyncRunModel.id.desc()).limit(1)
        )
    ).scalars().first()
    return await db.get(MetaSyncRunModel, run_id) if run_id else None


# --------------------------------------------------------------------------- #
# 计算入口
# --------------------------------------------------------------------------- #
async def _load_metric_context(metric_id: int, period_value: str | None, org_codes: list[str] | None) -> dict:
    """读取指标配置、来源对象与待算任务清单（只读，返回纯数据避免会话关闭后失效）。"""
    async with async_db_session() as db:
        metric = await db.get(MetricDefModel, metric_id)
        if metric is None:
            raise ValueError(f"指标定义不存在: {metric_id}")
        config = dict(metric.measures or {})
        kind = str(config.get("kind") or "")
        # 空 kind = 未配置取数规则（如口径待重新定义的指标）：允许存在，由调用方跳过计算
        if kind and kind not in SUPPORTED_KINDS:
            raise ValueError(f"暂不支持的指标取数类型: {kind}")
        period_type = metric.period_type or "month"
        period = period_value or current_period_value(period_type)
        resolve_period_datetime(period)  # 格式校验：YYYY / YYYY-MM / YYYY-MM-DD

        # 汇总/折算/比率指标没有自己的来源对象/同步任务，组成指标在配置里声明
        component_metrics: list[tuple[int, str]] = []
        numerator_metrics: list[tuple[int, str]] = []
        denominator_metrics: list[tuple[int, str]] = []
        numerator_subtrahend_metrics: list[tuple[int, str]] = []
        denominator_subtrahend_metrics: list[tuple[int, str]] = []
        addend_metrics: list[tuple[int, str]] = []
        subtrahend_metrics: list[tuple[int, str]] = []
        component_jobs: list[dict] = []
        job_rows: list = []
        source_object_id: int | None = None
        connection_id: int | None = None
        source_variables: list = []
        if not kind:
            pass
        elif kind in (
            METRIC_SUM_KIND,
            METRIC_SCALE_KIND,
            METRIC_RATIO_KIND,
            METRIC_RATIO_PERSON_KIND,
            METRIC_DIFF_KIND,
            METRIC_BALANCE_AVG_KIND,
        ):
            if kind in (METRIC_RATIO_KIND, METRIC_RATIO_PERSON_KIND):
                # 比率指标：分子与分母各是一组指标，分别求和后再相除；
                # 分子/分母还可各带一组减项（加项之和 − 减项之和），如安全边际率的分子是「总收益 − 盈亏平衡点销售额」
                numerator_codes = _normalize_metric_codes(config.get("numerator_metric_codes"))
                denominator_codes = _normalize_metric_codes(config.get("denominator_metric_codes"))
                numerator_subtrahend_codes = _normalize_metric_codes(
                    config.get("numerator_subtrahend_metric_codes")
                )
                denominator_subtrahend_codes = _normalize_metric_codes(
                    config.get("denominator_subtrahend_metric_codes")
                )
                if not numerator_codes or not denominator_codes:
                    raise ValueError(
                        f"比率指标缺少 numerator_metric_codes / denominator_metric_codes 配置: {metric.code}"
                    )
                codes = metric_dependency_codes(config)
            elif kind == METRIC_DIFF_KIND:
                # 差额指标：加项与减项各是一组指标，分别求和后再相减
                addend_codes = _normalize_metric_codes(config.get("addend_metric_codes"))
                subtrahend_codes = _normalize_metric_codes(config.get("subtrahend_metric_codes"))
                if not addend_codes and not subtrahend_codes:
                    raise ValueError(
                        f"差额指标缺少 addend_metric_codes / subtrahend_metric_codes 配置: {metric.code}"
                    )
                codes = metric_dependency_codes(config)
            else:
                codes = metric_dependency_codes(config)
                if not codes:
                    raise ValueError(f"汇总/折算指标缺少 component_metric_codes 配置: {metric.code}")
            rows = (
                await db.execute(
                    select(MetricDefModel.id, MetricDefModel.code).where(MetricDefModel.code.in_(codes))
                )
            ).all()
            id_by_code = {row[1]: row[0] for row in rows}
            for code in codes:
                if code not in id_by_code:
                    raise ValueError(f"组成指标不存在: {code}")
                if id_by_code[code] == metric.id:
                    raise ValueError(f"汇总指标不能把自己列为组成指标: {code}")
                component_metrics.append((id_by_code[code], code))
            if kind in (METRIC_RATIO_KIND, METRIC_RATIO_PERSON_KIND):
                numerator_metrics = [(id_by_code[code], code) for code in numerator_codes]
                denominator_metrics = [(id_by_code[code], code) for code in denominator_codes]
                numerator_subtrahend_metrics = [
                    (id_by_code[code], code) for code in numerator_subtrahend_codes
                ]
                denominator_subtrahend_metrics = [
                    (id_by_code[code], code) for code in denominator_subtrahend_codes
                ]
            elif kind == METRIC_DIFF_KIND:
                addend_metrics = [(id_by_code[code], code) for code in addend_codes]
                subtrahend_metrics = [(id_by_code[code], code) for code in subtrahend_codes]
        elif kind == BILL_AMOUNT_KIND:
            # 单据金额指标：``components`` 里每个来源对象各是一组同步任务，
            # 计算时分别取数、按各自口径过滤后合计成一个值（如采购入库单 + 收料通知单）。
            raw_components = config.get("components")
            if not isinstance(raw_components, list) or not raw_components:
                raise ValueError(f"单据金额指标缺少 components 配置: {metric.code}")
            has_component = False
            for comp in raw_components:
                if not isinstance(comp, dict):
                    raise ValueError(f"单据金额指标 components 配置项必须是对象: {metric.code}")
                comp_code = str(comp.get("source_object_code") or "").strip()
                comp_object = (
                    await db.execute(
                        select(SourceObjectModel.id).where(SourceObjectModel.code == comp_code)
                    )
                ).scalars().first()
                if comp_object is None:
                    raise ValueError(f"来源对象不存在: {comp_code}")
                comp_rows = (
                    await db.execute(
                        select(
                            MetaSyncJobModel.id,
                            MetaSyncJobModel.org_code,
                            MetaSyncJobModel.request_params,
                            MetaSyncJobModel.variables,
                        )
                        .where(
                            MetaSyncJobModel.source_object_id == comp_object,
                            MetaSyncJobModel.status == 0,
                        )
                        .order_by(MetaSyncJobModel.org_code.asc(), MetaSyncJobModel.id.asc())
                    )
                ).all()
                comp_jobs = [
                    (int(row[0]), str(row[1] or ""), dict(row[2] or {}), list(row[3] or []))
                    for row in comp_rows
                ]
                if comp_jobs:
                    has_component = True
                job_rows.extend(comp_rows)
                component_jobs.append(
                    {"config": dict(comp), "source_object_code": comp_code, "jobs": comp_jobs}
                )
            if not has_component:
                logger.warning(f"单据金额指标 {metric.code} 的组成来源都没有启用的同步任务")
        elif kind in CRM_PERSON_KINDS:
            # 业务员明细指标：``components`` 每项一个口径分支（内贸 / 外贸），
            # 分支里以 ``*_source_object_code`` 声明来源对象（订单明细、发货明细），
            # 计算时按各自来源的同步任务取该期间的原始明细，再按业务员分组。
            raw_components = config.get("components")
            if not isinstance(raw_components, list) or not raw_components:
                raise ValueError(f"业务员明细指标缺少 components 配置: {metric.code}")
            for comp in raw_components:
                if not isinstance(comp, dict):
                    raise ValueError(f"业务员明细指标 components 配置项必须是对象: {metric.code}")
                jobs_by_key: dict[str, list] = {}
                for key, value in comp.items():
                    # 兼容 ``source_object_code`` 与 ``order_source_object_code`` 这类带前缀的键
                    if "source_object_code" not in str(key):
                        continue
                    comp_code = _text(value)
                    if not comp_code:
                        continue
                    comp_object = (
                        await db.execute(select(SourceObjectModel.id).where(SourceObjectModel.code == comp_code))
                    ).scalars().first()
                    if comp_object is None:
                        raise ValueError(f"来源对象不存在: {comp_code}")
                    comp_rows = (
                        await db.execute(
                            select(
                                MetaSyncJobModel.id,
                                MetaSyncJobModel.org_code,
                                MetaSyncJobModel.request_params,
                                MetaSyncJobModel.variables,
                            )
                            .where(
                                MetaSyncJobModel.source_object_id == comp_object,
                                MetaSyncJobModel.status == 0,
                            )
                            .order_by(MetaSyncJobModel.org_code.asc(), MetaSyncJobModel.id.asc())
                        )
                    ).all()
                    jobs_by_key[str(key)] = [
                        (int(row[0]), str(row[1] or ""), dict(row[2] or {}), list(row[3] or []))
                        for row in comp_rows
                    ]
                    # 一并登记到 job_rows：让 ``_ensure_period_batches`` 能补当期缺的同步批次
                    job_rows.extend(comp_rows)
                # 指标级配置（value_mode / stat / lookback_periods 等）+ 分支级配置合并，
                # 分支同名键优先；这样取数执行器既能读分支口径，也能读到指标级开关
                component_jobs.append({"config": {**config, **comp}, "jobs_by_key": jobs_by_key})
            if not any(comp["jobs_by_key"].values() for comp in component_jobs):
                logger.warning(f"业务员明细指标 {metric.code} 的组成来源都没有启用的同步任务")
        else:
            source_object_code = str(config.get("source_object_code") or "")
            source_object = (
                await db.execute(
                    select(SourceObjectModel.id, SourceObjectModel.system_id).where(
                        SourceObjectModel.code == source_object_code
                    )
                )
            ).first()
            if source_object is None:
                raise ValueError(f"来源对象不存在: {source_object_code}")
            source_object_id, source_system_id = int(source_object[0]), int(source_object[1])
            if kind in (PRODUCTION_INSTOCK_KIND, AR_AGING_KIND):
                # 这两类指标要在计算时实时回查金蝶（生产订单头金额 / 账龄分析表），先取出连接配置
                connection_id = (
                    await db.execute(
                        select(SourceSystemModel.connection_id).where(SourceSystemModel.id == source_system_id)
                    )
                ).scalars().first()
            if kind == AR_AGING_KIND:
                # 账龄分析表在计算时实时取数，只需要来源对象的变量定义（如账龄截止日）
                source_variables = (
                    await db.execute(
                        select(SourceObjectModel.variables).where(SourceObjectModel.id == source_object_id)
                    )
                ).scalars().first()

            job_query = select(
                MetaSyncJobModel.id,
                MetaSyncJobModel.org_code,
                MetaSyncJobModel.request_params,
                MetaSyncJobModel.variables,
            ).where(
                MetaSyncJobModel.source_object_id == source_object_id,
                MetaSyncJobModel.status == 0,
            )
            # 组织范围：``measures.org_codes``（指标自带口径）与调用方传入的 ``org_codes``
            # （部分重算）取交集；两者都配置时以交集为准，交集为空则不取任何组织。
            config_org_codes = config.get("org_codes")
            if isinstance(config_org_codes, str):
                config_org_codes = [config_org_codes]
            config_org_codes = {
                str(code).strip() for code in (config_org_codes or []) if str(code).strip()
            }
            requested_org_codes = {str(code).strip() for code in (org_codes or []) if str(code).strip()}
            if config_org_codes or requested_org_codes:
                if config_org_codes and requested_org_codes:
                    allowed_org_codes = config_org_codes & requested_org_codes
                else:
                    allowed_org_codes = config_org_codes or requested_org_codes
                job_query = job_query.where(MetaSyncJobModel.org_code.in_(sorted(allowed_org_codes)))
            job_rows = (await db.execute(job_query.order_by(MetaSyncJobModel.org_code.asc()))).all()

        previous_version = (
            await db.execute(
                select(func.max(MetricValueModel.calc_version)).where(
                    MetricValueModel.metric_id == metric.id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                )
            )
        ).scalars().first()

    return {
        "metric_id": metric.id,
        "metric_code": metric.code,
        "metric_version": metric.version,
        "config": config,
        "period_type": period_type,
        "period": period,
        "signature": _config_signature({"kind": kind, "measures": metric.measures, "dimensions": metric.dimensions}),
        "jobs": [
            (int(row[0]), str(row[1] or ""), dict(row[2] or {}), list(row[3] or [])) for row in job_rows
        ],
        "source_object_code": str(config.get("source_object_code") or ""),
        "source_variables": list(source_variables or []),
        "component_metrics": component_metrics,
        "component_jobs": component_jobs,
        "numerator_metrics": numerator_metrics,
        "denominator_metrics": denominator_metrics,
        "numerator_subtrahend_metrics": numerator_subtrahend_metrics,
        "denominator_subtrahend_metrics": denominator_subtrahend_metrics,
        "addend_metrics": addend_metrics,
        "subtrahend_metrics": subtrahend_metrics,
        "source_object_id": source_object_id,
        "connection_id": connection_id,
        "previous_version": int(previous_version or 0),
    }


async def _ensure_period_batches(context: dict) -> list[str]:
    """确保每个组织都有该期间的同步批次；缺失的用期间覆盖变量回补一次。

    返回被回补的组织编码列表。
    """
    period = context["period"]
    missing: list[tuple[int, str]] = []
    async with async_db_session() as db:
        for job_id, org_code, _params, _variables in context["jobs"]:
            if await _latest_success_run(db, job_id, period) is None:
                missing.append((job_id, org_code))
    for job_id, org_code in missing:
        logger.info(f"指标 {context['metric_code']} 期间 {period} 缺少组织 {org_code} 的同步批次，按期间回补取数")
        await execute_meta_sync_job(job_id, period_value=period)
    return [org_code for _, org_code in missing]


async def _ensure_component_values(
    context: dict, period: str | None = None, *, require_fresh: bool = False
) -> list[str]:
    """汇总指标：确保组成指标在指定期间已有计算结果，缺失或过期的先算一次。

    每日 02:30 各指标的计算任务同点触发、先后顺序不确定；不先补齐时汇总指标可能
    读到其他期间的旧值甚至空值。这里按同一期间补齐，保证汇总口径与当期一致。
    ``period`` 缺省取指标当期；期初期末平均类指标还会传上一期（期初）。

    ``require_fresh=True``（当期计算使用）时，组成指标不仅要「有结果」，还要求结果
    是当天算出来的：否则派生指标先跑就会读到上一天 02:30 的旧版本，派生值滞后一天。
    上一期（期初）调用不带该要求——上期已结转，日复一日重算只是重复同口径取值。

    返回被临时补算的组成指标编码列表。
    """
    period = period or context["period"]
    period_type = context["period_type"]
    cutoff = local_day_start() if require_fresh else None
    stale: list[tuple[int, str, str]] = []
    async with async_db_session() as db:
        for component_id, code in context["component_metrics"]:
            latest_row = (
                await db.execute(
                    select(MetricValueModel.calc_version, MetricValueModel.calc_time)
                    .where(
                        MetricValueModel.metric_id == component_id,
                        MetricValueModel.period_type == period_type,
                        MetricValueModel.period_value == period,
                    )
                    .order_by(MetricValueModel.calc_version.desc(), MetricValueModel.id.desc())
                    .limit(1)
                )
            ).first()
            if latest_row is None:
                stale.append((component_id, code, "缺少结果"))
            elif cutoff is not None and (latest_row[1] is None or _as_utc(latest_row[1]) < cutoff):
                stale.append((component_id, code, "结果为当天之前"))
    for component_id, code, reason in stale:
        logger.info(
            f"汇总指标 {context['metric_code']} 期间 {period} 的组成指标 {code} {reason}，先计算该指标"
        )
        await execute_metric_calc(metric_id=component_id, period_value=period)
    return [code for _, code, _ in stale]


async def _sum_component_values(
    db, component_metrics: list[tuple[int, str]], period_type: str, period: str
) -> tuple[float, int]:
    """把组成指标该期间「最新版本的组织合计行」相加（``dept_code IS NULL`` 即合计层）。

    组成指标本身按组织拆分时，其各组织合计一并相加，等于该指标的公司整体值。
    返回 ``(合计值, 参与相加的行数)``。
    """
    total = 0.0
    row_count = 0
    for component_id, code in component_metrics:
        latest = (
            await db.execute(
                select(func.max(MetricValueModel.calc_version)).where(
                    MetricValueModel.metric_id == component_id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                )
            )
        ).scalars().first()
        if latest is None:
            logger.warning(f"组成指标 {code} 在 {period} 无计算结果，按 0 计入汇总")
            continue
        values = (
            await db.execute(
                select(MetricValueModel.value).where(
                    MetricValueModel.metric_id == component_id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                    MetricValueModel.calc_version == int(latest),
                    MetricValueModel.dept_code.is_(None),
                )
            )
        ).scalars().all()
        for value in values:
            total += float(value or 0)
            row_count += 1
    return round(total, 4), row_count


async def _sum_component_values_by_org(
    db, component_metrics: list[tuple[int, str]], period_type: str, period: str
) -> tuple[dict[int | None, float], int]:
    """按组织合计组成指标当期「最新版本的组织合计行」。

    返回 ``({org_id: 合计值}, 参与相加的行数)``；组织为 ``None`` 表示组成指标本身没有组织维度。
    """
    totals: dict[int | None, float] = {}
    row_count = 0
    for component_id, code in component_metrics:
        latest = (
            await db.execute(
                select(func.max(MetricValueModel.calc_version)).where(
                    MetricValueModel.metric_id == component_id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                )
            )
        ).scalars().first()
        if latest is None:
            logger.warning(f"组成指标 {code} 在 {period} 无计算结果，按 0 计入汇总")
            continue
        rows = (
            await db.execute(
                select(MetricValueModel.org_id, MetricValueModel.value).where(
                    MetricValueModel.metric_id == component_id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                    MetricValueModel.calc_version == int(latest),
                    MetricValueModel.dept_code.is_(None),
                )
            )
        ).all()
        for org_id, value in rows:
            totals[org_id] = totals.get(org_id, 0.0) + float(value or 0)
            row_count += 1
    return {org_id: round(value, 4) for org_id, value in totals.items()}, row_count


async def _load_run_payload(job_id: int, period_value: str) -> dict | None:
    """读取某同步任务在指定期间最近一次成功批次的原始返回（无批次返回 ``None``）。"""
    async with async_db_session() as db:
        run = await _latest_success_run(db, job_id, period_value)
        return dict(run.rows_json or {}) if run is not None else None


async def _aggregate_crm_person_amount(context: dict) -> dict:
    """业务员明细指标取数：按口径分支读同步批次明细，汇总成「业务员 → 指标值」。

    - ``crm_person_amount``：直接按订单明细的 ``create_id`` 分组（按建单月取当期批次）。
    - ``crm_shipment_person_amount``：先按订单明细建「订单号 → 业务员 / 未税单价」索引，
      再按发货明细结转（``value_mode`` = ``amount`` 金额 / ``qty`` 数量）；订单明细按
      ``lookback_periods`` 个期间回看（部分订单在发货月之前创建），缺失期间按需回补取数。
    - ``crm_order_push_person``：按订单的 **ERP 下推时间** 落在当期过滤（下单月与下推月
      通常不同月，同样按 ``lookback_periods`` 回看）；``stat`` = ``amount`` 输出下推金额，
      ``period_days`` 输出下推周期 = Σ(下推时间 − 建单时间) ÷ 下推订单数 —— 平均值不能逐单
      相加，因此业务员与公司合计都按「天数和 ÷ 订单数和」加权。
    """
    config = context["config"]
    kind = str(config.get("kind") or "")
    period = context["period"]
    period_type = context["period_type"]
    lookback = max(int(config.get("lookback_periods") or 1), 1)
    backfill_lookback = bool(config.get("backfill_lookback", True))
    is_push_kind = kind == CRM_ORDER_PUSH_PERSON_KIND
    is_quote_kind = kind == CRM_QUOTE_PERSON_KIND
    is_avg_mode = is_push_kind and str(config.get("stat") or "amount") == "period_days"
    quote_stat = str(config.get("stat") or "count")
    value_mode = str(config.get("value_mode") or "amount")
    is_customer_count = kind == CRM_PERSON_AMOUNT_KIND and value_mode == "count_customers"
    is_order_count = kind == CRM_PERSON_AMOUNT_KIND and value_mode == "count_orders"
    omit_zero = bool(config.get("omit_zero_persons", True))
    # 累加器：普通口径累加 value；平均口径累加 days / orders（orders 兼作行数）
    buckets: dict[str, dict] = {}
    matched_rows = 0
    missing_rows = 0
    missing_orders: set[str] = set()
    backfilled_periods: list[str] = []

    def merge(person_buckets: dict[str, dict]) -> None:
        for person, item in person_buckets.items():
            bucket = buckets.setdefault(person, {})
            for key, value in item.items():
                if key == "customers":
                    bucket.setdefault("customers", set()).update(value or ())
                elif isinstance(value, (int, float)):
                    bucket[key] = round(float(bucket.get(key) or 0) + float(value), 4)

    async def load_rows(job_id: int, period_value: str, allow_backfill: bool) -> list:
        """读某期批次明细；缺失且允许时按期间回补一次。"""
        payload = await _load_run_payload(job_id, period_value)
        if payload is None and allow_backfill and backfill_lookback:
            await execute_meta_sync_job(job_id, period_value=period_value)
            backfilled_periods.append(period_value)
            payload = await _load_run_payload(job_id, period_value)
        return (_payload_rows(payload) or []) if payload is not None else []

    async with async_db_session() as db:
        person_index = await _load_person_index(db)
    for comp in context["component_jobs"]:
        cfg = comp["config"]
        jobs_by_key = comp["jobs_by_key"]
        if kind == CRM_PERSON_AMOUNT_KIND:
            for job_id, _org_code, params, _variables in jobs_by_key.get("source_object_code") or []:
                rows = await load_rows(job_id, period, False)
                if not rows:
                    continue
                extracted = extract_person_amount(rows, _field_order(params), cfg)
                matched_rows += int(extracted["matched_rows"])
                merge(extracted["persons"])
            continue
        if is_push_kind:
            # 下推指标：订单按「下推时间落在当期」过滤，需要回看建单月（通常早于下推月）
            order_jobs = jobs_by_key.get("source_object_code") or []
            for offset in range(lookback):
                lookback_period = shift_period(period_type, period, -offset) if offset else period
                for job_id, _org_code, params, _variables in order_jobs:
                    rows = await load_rows(job_id, lookback_period, offset > 0)
                    if not rows:
                        continue
                    extracted = extract_push_person_stat(
                        rows, _field_order(params), cfg, period_type, period
                    )
                    matched_rows += int(extracted["matched_rows"])
                    merge(extracted["persons"])
            continue
        if is_quote_kind:
            # 报价指标：接口已按 status='E'（已审核）与报价月过滤，直接按业务员累加计数
            for job_id, _org_code, params, _variables in jobs_by_key.get("source_object_code") or []:
                rows = await load_rows(job_id, period, False)
                if not rows:
                    continue
                extracted = extract_quote_person_stat(rows, _field_order(params), cfg)
                matched_rows += int(extracted["matched_rows"])
                merge(extracted["persons"])
            continue
        # 发货明细：先回看订单明细建索引，再按发货明细结转
        order_index: dict[str, dict] = {}
        order_jobs = jobs_by_key.get("order_source_object_code") or []
        for offset in range(lookback):
            lookback_period = shift_period(period_type, period, -offset) if offset else period
            for job_id, _org_code, params, _variables in order_jobs:
                rows = await load_rows(job_id, lookback_period, offset > 0)
                if not rows:
                    continue
                for number, info in build_order_amount_index(rows, _field_order(params), cfg).items():
                    order_index.setdefault(number, info)
        for job_id, _org_code, params, _variables in jobs_by_key.get("shipment_source_object_code") or []:
            rows = await load_rows(job_id, period, False)
            if not rows:
                continue
            extracted = extract_shipment_person_amount(rows, order_index, cfg)
            matched_rows += int(extracted["matched_rows"])
            missing_rows += int(extracted["missing_rows"])
            missing_orders.update(extracted["missing_orders"])
            merge(extracted["persons"])
    persons: dict[str, dict] = {}
    for person, bucket in buckets.items():
        orders = int(bucket.get("orders") or 0)
        if is_customer_count:
            # 客户数按业务员去重（内贸/外贸同一客户只算一次）
            value = float(len(bucket.get("customers") or ()))
            rows = int(bucket.get("rows") or 0)
        elif is_order_count:
            value = float(int(bucket.get("rows") or 0))
            rows = int(bucket.get("rows") or 0)
        elif is_quote_kind:
            value = _quote_person_value(quote_stat, bucket)
            rows = int(bucket.get("count") or 0)
        elif is_avg_mode:
            value = round(float(bucket["days"]) / orders, 4) if orders else 0.0
            rows = orders
        else:
            value = round(float(bucket.get("value") or 0), 4)
            rows = int(bucket.get("rows") or 0)
        if omit_zero and value == 0:
            continue
        persons[person] = {"value": value, "rows": rows}
    person_meta: dict[str, dict] = {}
    for person_key in persons:
        person_meta[person_key] = person_index.get(person_key) or {
            "person_id": None,
            "person_code": f"CRM{person_key}" if person_key else "未指定业务员",
            "person_name": f"CRM{person_key}" if person_key else "未指定业务员",
        }
    total_orders = sum(int(bucket.get("orders") or 0) for bucket in buckets.values())
    total_days = round(sum(float(bucket.get("days") or 0) for bucket in buckets.values()), 4)
    if is_avg_mode:
        # 公司口径平均下推周期 = Σ天数 ÷ Σ订单数（不是各业务员周期的平均）
        total = round(total_days / total_orders, 4) if total_orders else 0.0
    elif is_customer_count:
        # 公司口径客户数 = 全部业务员客户并集（同一客户被多人跟过只算一次）
        all_customers: set = set()
        for bucket in buckets.values():
            all_customers |= bucket.get("customers") or set()
        total = float(len(all_customers))
    elif is_quote_kind:
        # 报价类：公司合计同样按 Σ分子 ÷ Σ分母（不能把各业务员的比率相加）
        total_bucket: dict = {}
        for bucket in buckets.values():
            for key, value in bucket.items():
                if isinstance(value, (int, float)):
                    total_bucket[key] = float(total_bucket.get(key) or 0) + float(value)
        total = _quote_person_value(quote_stat, total_bucket)
    else:
        total = round(sum(float(bucket["value"]) for bucket in persons.values()), 4)
    return {
        "persons": persons,
        "person_meta": person_meta,
        "total": total,
        "matched_rows": matched_rows,
        "missing_rows": missing_rows,
        "missing_orders": sorted(missing_orders),
        "backfilled_periods": sorted(set(backfilled_periods)),
        "lookback_periods": lookback,
        "person_count": len(persons),
        "push_orders": total_orders if is_push_kind else 0,
    }


async def _load_person_metric_rows(
    db, component_metrics: list[tuple[int, str]], period_type: str, period: str
) -> dict[str, dict]:
    """读取若干个业务员维度指标当期「最新版本」的业务员行，合并成 ``{业务员编码: 值+主数据}``。"""
    merged: dict[str, dict] = {}
    for component_id, _code in component_metrics:
        latest = (
            await db.execute(
                select(func.max(MetricValueModel.calc_version)).where(
                    MetricValueModel.metric_id == component_id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                )
            )
        ).scalars().first()
        if latest is None:
            continue
        rows = (
            await db.execute(
                select(
                    MetricValueModel.person_code,
                    MetricValueModel.person_name,
                    MetricValueModel.person_id,
                    MetricValueModel.value,
                ).where(
                    MetricValueModel.metric_id == component_id,
                    MetricValueModel.period_type == period_type,
                    MetricValueModel.period_value == period,
                    MetricValueModel.calc_version == int(latest),
                    MetricValueModel.person_code.is_not(None),
                )
            )
        ).all()
        for person_code, person_name, person_id, value in rows:
            key = _text(person_code)
            item = merged.setdefault(
                key, {"value": 0.0, "person_name": person_name, "person_id": person_id}
            )
            item["value"] = round(float(item["value"]) + float(value or 0), 4)
    return merged


async def _compute_person_ratio(
    db, context: dict, period_type: str, period: str
) -> dict:
    """业务员比率：分子合计 ÷ 分母合计 × ratio_scale，**按业务员分别计算**。

    分母为 0（或该业务员分母指标没有行）时跳过该业务员；公司合计 = Σ分子 ÷ Σ分母 × scale。
    """
    config = context["config"]
    scale = float(config.get("ratio_scale") or 1)
    numerators = await _load_person_metric_rows(db, context["numerator_metrics"], period_type, period)
    denominators = await _load_person_metric_rows(db, context["denominator_metrics"], period_type, period)
    person_meta: dict[str, dict] = {}
    persons: dict[str, dict] = {}
    total_num = 0.0
    total_den = 0.0
    for person, item in denominators.items():
        denominator = float(item["value"] or 0)
        if denominator == 0:
            continue
        numerator = float((numerators.get(person) or {}).get("value") or 0)
        persons[person] = {
            "value": round(numerator / denominator * scale, 4),
            "rows": 1,
            "numerator": round(numerator, 4),
            "denominator": round(denominator, 4),
        }
        person_meta[person] = {
            "person_id": item.get("person_id"),
            "person_code": person or "未指定业务员",
            "person_name": _text(item.get("person_name")) or person or "未指定业务员",
        }
        total_num += numerator
        total_den += denominator
    total = round(total_num / total_den * scale, 4) if total_den else 0.0
    return {
        "persons": persons,
        "person_meta": person_meta,
        "total": total,
        "matched_rows": len(persons),
        "missing_rows": 0,
        "missing_orders": [],
        "backfilled_periods": [],
        "lookback_periods": 1,
        "person_count": len(persons),
        "total_numerator": round(total_num, 4),
        "total_denominator": round(total_den, 4),
    }


async def refresh_period_batches(metric_id: int, period_value: str) -> list[str]:
    """强制重跑该指标所有同步任务在指定期间的取数批次。

    与 :func:`_ensure_period_batches` 不同：这里**不做「已有批次就复用」的判断**，
    用于次月 1 日结账——上月的批次是上月最后一天 02:00 拉的，必须重拉才能把
    月末当天白天产生的单据（出库单、费用凭证）补进来。

    返回被刷新取数的组织编码列表。
    """
    context = await _load_metric_context(metric_id, period_value, None)
    if str(context["config"].get("kind") or "") in LIVE_KINDS:
        # 实时取数类指标（账龄计提）没有同步批次，重拉不适用
        return []
    refreshed: list[str] = []
    for job_id, org_code, _params, _variables in context["jobs"]:
        await execute_meta_sync_job(job_id, period_value=period_value)
        refreshed.append(org_code)
    return refreshed


async def _fetch_live_aging_payloads(context: dict, as_of: date) -> dict[int, dict]:
    """按组织实时拉取《应收款账龄分析表》按单据数据（只读，不写同步批次）。

    账龄分析表一次全量约 7MB/组织，按天落库会迅速撑大 ``meta_sync_run``，
    因此这里在计算时按组织并发取数，只保留计算结果。组织与结算组织内码
    由该来源对象下的同步任务登记（``variables.settle_org_id``）。
    """
    if not context["connection_id"]:
        raise ValueError("账龄计提指标缺少金蝶连接配置")
    async with async_db_session() as db:
        connection = await db.get(KingdeeConnectionModel, int(context["connection_id"]))
    if connection is None:
        raise ValueError(f"金蝶连接配置不存在: {context['connection_id']}")
    client = KingdeeService._client_from(connection)
    form_id = context["source_object_code"] or "AR_AgingAnalysis"
    run_now = resolve_period_datetime(context["period"]) or datetime.now()
    concurrency = max(1, int(context["config"].get("max_concurrency") or 3))
    semaphore = asyncio.Semaphore(concurrency)

    async def load(job: tuple) -> tuple[int, dict]:
        job_id, org_code, request_params, job_variables = job
        # 账龄截止日由引擎算好注入，保证取数与计提用的是同一天
        variables = merge_variables(
            context["source_variables"],
            job_variables,
            [{"name": "aging_date", "value_type": "string", "value": as_of.isoformat()}],
        )
        params = render_request_params(request_params or {}, org_code, variables, now=run_now)
        async with semaphore:
            report = await fetch_report_data(client, form_id, params)
        logger.info(
            f"账龄计提指标 {context['metric_code']} 组织 {org_code} 实时取数 {report.get('RowCount')} 行"
        )
        return int(job_id), report

    pairs = await asyncio.gather(*(load(job) for job in context["jobs"]))
    return dict(pairs)


async def execute_metric_calc(
    metric_id: int,
    period_value: str | None = None,
    org_codes: list[str] | None = None,
) -> dict:
    """计算指标并写入 ``metric_value``（带依赖环保护的外层入口）。

    派生指标在计算前会递归补算组成指标（见 :func:`_ensure_component_values`），
    若 ``measures`` 配置成环（A 依赖 B、B 又依赖 A）会无限递归。这里用 ContextVar
    记录本次调用链：组成指标若已在链上，说明存在环，直接报错并中止该指标计算。
    同一条链上的递归不会重复入栈，正常的多层派生（汇总嵌套汇总）不受影响。
    """
    chain = CALC_CHAIN.get()
    if metric_id in chain:
        path = " -> ".join(str(item) for item in (*chain, metric_id))
        raise ValueError(f"指标依赖存在环，已中止计算（调用链 {path}）")
    token = CALC_CHAIN.set((*chain, metric_id))
    try:
        return await _execute_metric_calc_inner(metric_id, period_value, org_codes)
    finally:
        CALC_CHAIN.reset(token)


async def _execute_metric_calc_inner(
    metric_id: int,
    period_value: str | None = None,
    org_codes: list[str] | None = None,
) -> dict:
    """计算指标并写入 ``metric_value``。

    参数:
    - metric_id (int): 指标定义ID。
    - period_value (str | None): 期间值，缺省取当前期间（月指标 → ``YYYY-MM``）。
    - org_codes (list[str] | None): 限定组织编码，缺省计算全部启用组织。

    返回:
    - dict: 计算摘要（期间、版本、各组织结果、跳过组织、批次ID）。
    """
    context = await _load_metric_context(metric_id, period_value, org_codes)
    config = context["config"]
    kind = str(config.get("kind") or "")
    period_type = context["period_type"]
    period = context["period"]
    signature = context["signature"]
    if not kind:
        # 未配置取数规则的指标（口径待定义/已迁移）：不写结果、不报错，只记一条警告
        logger.warning(
            f"指标 {context['metric_code']} 未配置取数规则(measures.kind)，跳过 {period} 计算"
        )
        return {
            "metric_id": context["metric_id"],
            "metric_code": context["metric_code"],
            "period_type": period_type,
            "period_value": period,
            "calc_version": context["previous_version"],
            "batch_id": "",
            "skipped": True,
            "reason": "未配置取数规则(measures.kind 为空)",
            "total": 0,
            "orgs": {},
        }
    # 实时取数类指标（账龄计提）不依赖同步批次，跳过批次回补
    backfilled = [] if kind in LIVE_KINDS else await _ensure_period_batches(context)
    # 汇总/折算/比率指标：先把组成指标当期结果补齐，再开写入事务
    balance_begin_period: str | None = None
    if kind == METRIC_BALANCE_AVG_KIND:
        # 期初期末平均：期初取上一期组成指标结果，先补齐上一期
        balance_begin_period = shift_period(period_type, period, -1)
    backfilled_components: list[str] = []
    if kind in (
        METRIC_SUM_KIND,
        METRIC_SCALE_KIND,
        METRIC_RATIO_KIND,
        METRIC_RATIO_PERSON_KIND,
        METRIC_DIFF_KIND,
    ):
        # 当期组成指标必须是「今天算的」，否则派生值会滞后一天
        backfilled_components = await _ensure_component_values(context, require_fresh=True)
    elif kind == METRIC_BALANCE_AVG_KIND:
        backfilled_components = await _ensure_component_values(context, require_fresh=True)
        # 期初那一期不要求新鲜度：上期已结转，只要该期间有结果即可
        backfilled_components += await _ensure_component_values(context, balance_begin_period)
    # 生产入库指标：先从各任务的期间批次里读出单据行，收集生产订单号并一次性回查订单头金额。
    # 放在写入事务之前，避免网络取数期间占用写事务。
    prefetched_payloads: dict[int, dict] = {}
    order_facts: dict[str, dict] = {}
    missing_order_count = 0
    aging_as_of: date | None = None
    if kind == AR_AGING_KIND:
        # 账龄截止日 = 期末日；当期未到期末则取今天（每日重算当月时的实际账龄）
        aging_as_of = min(date.today(), period_end_date(period_type, period))
        prefetched_payloads = await _fetch_live_aging_payloads(context, aging_as_of)
    if kind == PRODUCTION_INSTOCK_KIND:
        order_numbers: set[str] = set()
        async with async_db_session() as db:
            for job_id, _org_code, request_params, _variables in context["jobs"]:
                source_run = await _latest_success_run(db, job_id, period)
                payload = dict(source_run.rows_json or {}) if source_run else {}
                prefetched_payloads[job_id] = payload
                fields = _field_order(request_params)
                picked = select_demand_rows(_payload_rows(payload) or [], fields, config)
                order_numbers |= production_order_numbers(picked, fields, config)
        order_facts, missing_order_count = await fetch_production_order_facts(
            context["connection_id"], sorted(order_numbers), config
        )
        if missing_order_count:
            logger.warning(
                f"指标 {context['metric_code']} 期间 {period} 有 {missing_order_count} 张生产订单未取到订单信息"
            )
    person_result: dict = {}
    if kind in CRM_PERSON_KINDS:
        # 业务员明细：写入事务前先完成全部取数/聚合，避免网络取数期间占用写事务
        person_result = await _aggregate_crm_person_amount(context)
        if person_result["missing_rows"]:
            logger.warning(
                f"指标 {context['metric_code']} 期间 {period} 有 {person_result['missing_rows']} 行发货明细"
                f"关联不到订单（订单创建月早于 {person_result['lookback_periods']} 期回看窗口）"
            )
    if kind == METRIC_RATIO_PERSON_KIND:
        # 业务员比率：读分子/分母指标当期的业务员行，按人相除（只读，用独立会话）
        async with async_db_session() as ratio_db:
            person_result = await _compute_person_ratio(ratio_db, context, period_type, period)

    async with async_db_session() as db, db.begin():
        metric_id = context["metric_id"]
        batch_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        run = MetricRunModel(
            metric_id=metric_id,
            period_type=period_type,
            period_value=period,
            version=context["metric_version"],
            batch_id=batch_id,
            filter_signature=signature,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()

        # 全量重算开一个新版本；单组织重算沿用当前版本并替换该组织的行，
        # 否则“取最新版本”的查询会只剩被重算的组织。
        partial = bool(org_codes)
        calc_version = context["previous_version"] if partial else context["previous_version"] + 1
        calc_version = calc_version or 1

        org_id_map = {
            org_code: await _resolve_org_id(db, org_code) for _, org_code, _params, _variables in context["jobs"]
        }
        if partial:
            affected = [org_id for org_id in org_id_map.values() if org_id is not None]
            if affected:
                await db.execute(
                    delete(MetricValueModel).where(
                        MetricValueModel.metric_id == metric_id,
                        MetricValueModel.period_type == period_type,
                        MetricValueModel.period_value == period,
                        MetricValueModel.calc_version == calc_version,
                        MetricValueModel.org_id.in_(affected),
                    )
                )

        results: dict[str, dict] = {}
        skipped: list[str] = []
        if kind == METRIC_RATIO_KIND:
            # 比率指标：分子合计 ÷ 分母合计 × ratio_scale（分母为 0 时取 0，避免除零）；
            # 分子/分母各自可带减项：净额 = 加项之和 − 减项之和
            numerator, _numerator_rows = await _sum_component_values(
                db, context["numerator_metrics"], period_type, period
            )
            denominator, denominator_rows = await _sum_component_values(
                db, context["denominator_metrics"], period_type, period
            )
            if context["numerator_subtrahend_metrics"]:
                numerator_deduct, deduct_rows = await _sum_component_values(
                    db, context["numerator_subtrahend_metrics"], period_type, period
                )
                numerator = round(numerator - numerator_deduct, 4)
                denominator_rows += deduct_rows
            if context["denominator_subtrahend_metrics"]:
                denominator_deduct, deduct_rows = await _sum_component_values(
                    db, context["denominator_subtrahend_metrics"], period_type, period
                )
                denominator = round(denominator - denominator_deduct, 4)
                denominator_rows += deduct_rows
            ratio_scale = float(config.get("ratio_scale") or 1)
            total = round(numerator / denominator * ratio_scale, 4) if denominator else 0.0
            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=None,
                    value=total,
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            results[""] = {
                "org_id": None,
                "total": total,
                "matched_rows": denominator_rows,
                "departments": 0,
                "numerator": numerator,
                "denominator": denominator,
                "components": [code for _, code in context["component_metrics"]],
            }
        elif kind == METRIC_RATIO_PERSON_KIND:
            # 业务员比率：按业务员分别相除（复购率 = 本月下单老客户数 ÷ 总客户数）
            persons = person_result.get("persons") or {}
            person_meta = person_result.get("person_meta") or {}
            total = round(float(person_result.get("total") or 0), 4)
            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=None,
                    value=total,
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            for person_key in sorted(persons):
                bucket = persons[person_key]
                meta = person_meta.get(person_key) or {}
                person_code = _text(meta.get("person_code")) or person_key or "未指定业务员"
                person_name = _text(meta.get("person_name")) or person_code
                person_id = meta.get("person_id")
                db.add(
                    MetricValueModel(
                        metric_id=metric_id,
                        run_id=run.id,
                        period_type=period_type,
                        period_value=period,
                        org_id=None,
                        dept_id=person_id,
                        dept_code=person_code,
                        dept_name=person_name,
                        person_id=person_id,
                        person_code=person_code,
                        person_name=person_name,
                        value=bucket["value"],
                        version=context["metric_version"],
                        calc_version=calc_version,
                        batch_id=batch_id,
                        filter_signature=signature,
                        calc_time=datetime.now(UTC),
                    )
                )
            results[""] = {
                "org_id": None,
                "total": total,
                "matched_rows": person_result.get("matched_rows", 0),
                "numerator": person_result.get("total_numerator", 0),
                "denominator": person_result.get("total_denominator", 0),
                "persons": person_result.get("person_count", 0),
                "components": [code for _, code in context["component_metrics"]],
            }
        elif kind == METRIC_DIFF_KIND:
            # 差额指标：加项合计 − 减项合计（如边际贡献 = 总收益（营销结算收入）− 变动费用合计）
            addend_total, addend_rows = await _sum_component_values(
                db, context["addend_metrics"], period_type, period
            )
            subtrahend_total, subtrahend_rows = await _sum_component_values(
                db, context["subtrahend_metrics"], period_type, period
            )
            total = round(addend_total - subtrahend_total, 4)
            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=None,
                    value=total,
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            results[""] = {
                "org_id": None,
                "total": total,
                "matched_rows": addend_rows + subtrahend_rows,
                "departments": 0,
                "addend": addend_total,
                "subtrahend": subtrahend_total,
                "components": [code for _, code in context["component_metrics"]],
            }
        elif kind == METRIC_BALANCE_AVG_KIND:
            # 期初期末平均：期初 = 上一期组成指标合计，期末 = 当期组成指标合计；
            # 默认各取 0.5（平均库存 =（期初 + 期末）÷ 2），可用 begin_weight/end_weight 调整。
            begin_weight = float(config.get("begin_weight", 0.5))
            end_weight = float(config.get("end_weight", 0.5))
            begin_total, begin_rows = await _sum_component_values(
                db, context["component_metrics"], period_type, balance_begin_period or period
            )
            end_total, end_rows = await _sum_component_values(
                db, context["component_metrics"], period_type, period
            )
            total = round(begin_weight * begin_total + end_weight * end_total, 4)
            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=None,
                    value=total,
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            results[""] = {
                "org_id": None,
                "total": total,
                "matched_rows": begin_rows + end_rows,
                "departments": 0,
                "begin_period": balance_begin_period,
                "begin_total": begin_total,
                "end_total": end_total,
                "components": [code for _, code in context["component_metrics"]],
            }
        elif kind in (METRIC_SUM_KIND, METRIC_SCALE_KIND):
            # 汇总/折算指标没有来源行，直接合计组成指标当期组织合计行；
            # group_by_org=true 时按组织分别汇总（报表按组织行展示时需要）；
            # 折算指标（metric_scale）再把结果乘 scale 系数（如总收益 = 净额 × 10%）
            component_codes = [code for _, code in context["component_metrics"]]
            scale = float(config.get("scale") or 1) if kind == METRIC_SCALE_KIND else 1.0
            if config.get("group_by_org"):
                per_org, component_rows = await _sum_component_values_by_org(
                    db, context["component_metrics"], period_type, period
                )
                per_org = {org_id: round(value * scale, 4) for org_id, value in per_org.items()}
                for org_id, value in sorted(per_org.items(), key=lambda item: (item[0] is None, item[0])):
                    db.add(
                        MetricValueModel(
                            metric_id=metric_id,
                            run_id=run.id,
                            period_type=period_type,
                            period_value=period,
                            org_id=org_id,
                            value=value,
                            version=context["metric_version"],
                            calc_version=calc_version,
                            batch_id=batch_id,
                            filter_signature=signature,
                            calc_time=datetime.now(UTC),
                        )
                    )
                    results[str(org_id or "")] = {
                        "org_id": org_id,
                        "total": value,
                        "matched_rows": component_rows,
                        "departments": 0,
                        "components": component_codes,
                    }
                total = round(sum(per_org.values()), 4)
            else:
                total, component_rows = await _sum_component_values(
                    db, context["component_metrics"], period_type, period
                )
                total = round(total * scale, 4)
                db.add(
                    MetricValueModel(
                        metric_id=metric_id,
                        run_id=run.id,
                        period_type=period_type,
                        period_value=period,
                        org_id=None,
                        value=total,
                        version=context["metric_version"],
                        calc_version=calc_version,
                        batch_id=batch_id,
                        filter_signature=signature,
                        calc_time=datetime.now(UTC),
                    )
                )
                results[""] = {
                    "org_id": None,
                    "total": total,
                    "matched_rows": component_rows,
                    "departments": 0,
                    "components": component_codes,
                }
        elif kind == BILL_AMOUNT_KIND:
            # 单据金额指标：各来源对象分别取数（按各自 row_filters / dedupe 规则汇总），再把组成合计
            # 成一个值（公司整体口径，org_id 为空）。组成明细写进 summary 便于穿透核对。
            total = 0.0
            matched_rows = 0
            component_details: list[dict] = []
            for comp in context["component_jobs"]:
                comp_total = 0.0
                comp_rows = 0
                for job_id, _org_code, request_params, _variables in comp["jobs"]:
                    source_run = await _latest_success_run(db, job_id, period)
                    payload = (source_run.rows_json or {}) if source_run else {}
                    rows = _payload_rows(payload)
                    if rows is None:
                        continue
                    extracted = extract_bill_amount(rows, _field_order(request_params), comp["config"])
                    comp_total += float(extracted["total"])
                    comp_rows += int(extracted["matched_rows"])
                total += comp_total
                matched_rows += comp_rows
                component_details.append(
                    {
                        "source_object_code": comp["source_object_code"],
                        "label": str(comp["config"].get("label") or comp["source_object_code"]),
                        "total": round(comp_total, 4),
                        "matched_rows": comp_rows,
                    }
                )
            total = round(total, 4)
            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=None,
                    value=total,
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            results[""] = {
                "org_id": None,
                "total": total,
                "matched_rows": matched_rows,
                "departments": 0,
                "components": component_details,
            }
        if kind in CRM_PERSON_KINDS:
            # 业务员明细：写「公司合计行（dept_code 为空）+ 每业务员一行（dept_code = 业务员编码）」；
            # 明细行带 person_code，开放接口按 level=person 取，组织/部门层查询会自动排除。
            person_buckets = person_result.get("persons") or {}
            person_meta = person_result.get("person_meta") or {}
            # 合计取取数阶段算好的口径：普通指标 = Σ业务员值；下推周期 = Σ天数 ÷ Σ订单数
            # （不能把各业务员的平均周期直接相加）
            total = round(float(person_result.get("total") or 0), 4)
            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=None,
                    value=total,
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            for person_key in sorted(person_buckets):
                bucket = person_buckets[person_key]
                meta = person_meta.get(person_key) or {}
                person_code = _text(meta.get("person_code")) or f"CRM{person_key}"
                person_name = _text(meta.get("person_name")) or person_code
                person_id = meta.get("person_id")
                db.add(
                    MetricValueModel(
                        metric_id=metric_id,
                        run_id=run.id,
                        period_type=period_type,
                        period_value=period,
                        org_id=None,
                        dept_id=person_id,
                        dept_code=person_code,
                        dept_name=person_name,
                        person_id=person_id,
                        person_code=person_code,
                        person_name=person_name,
                        value=bucket["value"],
                        version=context["metric_version"],
                        calc_version=calc_version,
                        batch_id=batch_id,
                        filter_signature=signature,
                        calc_time=datetime.now(UTC),
                    )
                )
            results[""] = {
                "org_id": None,
                "total": total,
                "matched_rows": person_result.get("matched_rows", 0),
                "missing_rows": person_result.get("missing_rows", 0),
                "missing_orders": person_result.get("missing_orders", []),
                "persons": person_result.get("person_count", 0),
                "lookback_periods": person_result.get("lookback_periods", 1),
                "backfilled_periods": person_result.get("backfilled_periods", []),
            }
        for job_id, org_code, request_params, _variables in (
            []
            if kind == BILL_AMOUNT_KIND or kind in CRM_PERSON_KINDS
            else context["jobs"]
        ):
            if job_id in prefetched_payloads:
                payload = prefetched_payloads[job_id]
            else:
                source_run = await _latest_success_run(db, job_id, period)
                payload = (source_run.rows_json or {}) if source_run else {}
            if kind == API_SCALAR_KIND:
                # 单值接口（如 CRM 订单未税金额）：响应里只有一个数值，没有行结构
                extracted = extract_api_scalar(payload, config)
            else:
                rows = _payload_rows(payload)
                if rows is None:
                    skipped.append(org_code)
                    continue
                fields = _field_order(request_params)
                if kind == SALES_OUTBOUND_KIND:
                    extracted = extract_sales_outbound(rows, config)
                elif kind == PRODUCTION_INSTOCK_KIND:
                    extracted = extract_production_instock(rows, fields, config, order_facts)
                elif kind == AR_AGING_KIND:
                    extracted = extract_ar_aging_provision(
                        rows, fields, config, aging_as_of or date.today()
                    )
                elif kind == INVENTORY_LEDGER_KIND:
                    extracted = extract_inventory_ledger(rows, fields, config)
                else:
                    extracted = extract_account_balance(rows, fields, config)
            org_id = org_id_map.get(org_code)

            db.add(
                MetricValueModel(
                    metric_id=metric_id,
                    run_id=run.id,
                    period_type=period_type,
                    period_value=period,
                    org_id=org_id,
                    value=extracted["total"],
                    version=context["metric_version"],
                    calc_version=calc_version,
                    batch_id=batch_id,
                    filter_signature=signature,
                    calc_time=datetime.now(UTC),
                )
            )
            # 非部门维度（如客户、店铺）不做 master_dept 映射：省掉每个维度一次查询
            is_dept_dim = bool(config.get("detail_is_department", kind == ACCOUNT_BALANCE_KIND))
            for dept_code, bucket in extracted["departments"].items():
                dept_id = await _resolve_dept_id(db, org_id, dept_code) if is_dept_dim else None
                db.add(
                    MetricValueModel(
                        metric_id=metric_id,
                        run_id=run.id,
                        period_type=period_type,
                        period_value=period,
                        org_id=org_id,
                        dept_id=dept_id,
                        dept_code=dept_code or None,
                        dept_name=str(bucket.get("name") or "") or None,
                        value=bucket["value"],
                        version=context["metric_version"],
                        calc_version=calc_version,
                        batch_id=batch_id,
                        filter_signature=signature,
                        calc_time=datetime.now(UTC),
                    )
                )
            results[org_code] = {
                "org_id": org_id,
                "total": extracted["total"],
                "matched_rows": extracted["matched_rows"],
                "departments": len(extracted["departments"]),
            }
            if kind == SALES_OUTBOUND_KIND:
                results[org_code]["order_count"] = extracted["order_count"]
                results[org_code]["tax_inclusive_amount"] = extracted.get("tax_inclusive_amount", 0)
                results[org_code]["item_qty"] = extracted.get("item_qty", 0)
            if kind == PRODUCTION_INSTOCK_KIND:
                results[org_code]["inbound_rows"] = extracted.get("inbound_rows", 0)
                results[org_code]["order_count"] = extracted.get("order_count", 0)
                results[org_code]["deduped_orders"] = extracted.get("deduped_orders", 0)
                results[org_code]["fallback_orders"] = extracted.get("fallback_orders", 0)
                results[org_code]["missing_orders"] = len(extracted.get("missing_orders") or [])
            if kind == AR_AGING_KIND:
                results[org_code]["amount_total"] = extracted.get("amount_total", 0)
                results[org_code]["as_of"] = extracted.get("as_of", "")
                results[org_code]["missing_date"] = extracted.get("missing_date", 0)
                results[org_code]["netting"] = extracted.get("netting", "")
                results[org_code]["excluded_customers"] = extracted.get("excluded_customers", 0)
                results[org_code]["buckets"] = {
                    label: round(float(stat.get("provision") or 0), 4)
                    for label, stat in (extracted.get("buckets") or {}).items()
                }
                results[org_code]["bucket_amounts"] = {
                    label: round(float(stat.get("amount") or 0), 4)
                    for label, stat in (extracted.get("buckets") or {}).items()
                }
            if kind == INVENTORY_LEDGER_KIND:
                results[org_code]["qty_total"] = extracted.get("qty_total", 0)

        run.status = "success"
        run.finished_at = datetime.now(UTC)
        summary = {
            "metric_id": metric_id,
            "metric_code": context["metric_code"],
            "period_type": period_type,
            "period_value": period,
            "calc_version": calc_version,
            "batch_id": batch_id,
            "partial": partial,
            "backfilled_orgs": backfilled,
            "backfilled_components": backfilled_components,
            "missing_orders": missing_order_count,
            "org_count": len(results),
            "skipped_orgs": skipped,
            "total": round(sum(item["total"] for item in results.values()), 4),
            "orgs": results,
        }
        if kind == AR_AGING_KIND:
            summary["aging_as_of"] = aging_as_of.isoformat() if aging_as_of else None
            summary["amount_total"] = round(
                sum(float(item.get("amount_total") or 0) for item in results.values()), 4
            )
            summary["buckets"] = {
                label: round(sum(float(item.get("buckets", {}).get(label) or 0) for item in results.values()), 4)
                for label in (next(iter(results.values()), {}).get("buckets") or {})
            }
    logger.info(
        f"指标计算完成 {summary['metric_code']} {summary['period_value']} v{summary['calc_version']} "
        f"组织 {summary['org_count']} 合计 {summary['total']}"
    )
    return summary
