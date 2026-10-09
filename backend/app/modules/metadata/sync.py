"""元数据同步任务执行与 APScheduler 注册。"""

import asyncio
import ast
import re
from datetime import UTC, date, datetime, timedelta

from apscheduler.triggers.cron import CronTrigger

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger
from app.modules.crm.model import CrmConnectionModel
from app.modules.crm.service import build_client as build_crm_client
from app.modules.erp.jushuitan.model import JushuitanConnectionModel
from app.modules.erp.jushuitan.service import fetch_sales_outbound_rows
from app.modules.erp.kingdee.client import KingdeeBillQueryRequest, KingdeeClient
from app.modules.erp.kingdee.model import KingdeeConnectionModel
from app.modules.erp.kingdee.service import KingdeeService

from .model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel, SourceSystemModel

META_SYNC_JOB_PREFIX = "meta_sync:"

# 金蝶报表是分页返回的：单次请求只会返回 Limit 行，必须用 StartRow 翻页取全量。
# 历史上只取第一页（Limit=2000），导致科目余额表的 5xxx/6xxx 科目整段丢失。
SYNC_PAGE_SIZE = 2000
SYNC_MAX_PAGES = 200
# 金蝶报表接口偶发读超时（公有云网络抖动）：失败重试次数与退避基数
SYNC_RETRY_TIMES = 3
SYNC_RETRY_DELAY = 2.0


def _build_trigger(cron_expr: str) -> CronTrigger:
    fields = (cron_expr or "").strip().split()
    if len(fields) == 5:
        fields = ["0", *fields]
    if len(fields) not in (6, 7):
        raise ValueError("Cron 表达式格式错误，应为 5/6/7 段")
    fields = [field if field != "?" else "*" for field in fields]
    if len(fields) == 6:
        fields.append("*")
    second, minute, hour, day, month, day_of_week, year = fields
    return CronTrigger(
        second=second,
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        year=year,
        timezone="Asia/Shanghai",
    )


def register_meta_sync_job(job: MetaSyncJobModel) -> None:
    """按元数据任务配置注册/刷新 APScheduler 任务。"""
    job_id = f"{META_SYNC_JOB_PREFIX}{job.id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    if job.status == 1 or not job.cron_expr:
        return
    scheduler.add_job(
        func=execute_meta_sync_job,
        args=[job.id],
        trigger=_build_trigger(job.cron_expr),
        id=job_id,
        name=job.name,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


def unregister_meta_sync_job(job_id: int) -> None:
    try:
        scheduler.remove_job(f"{META_SYNC_JOB_PREFIX}{job_id}")
    except Exception:
        pass


def build_variable_context(variables: list[dict] | None, org_code: str | None = None, now: datetime | None = None) -> dict:
    """把变量定义转换为表达式上下文。

    ``now`` 用于覆盖取数时点：按期间回补历史数据时，模板里的 ``{{year}}``/``{{month}}``
    必须渲染成目标期间，而不是当前时间。
    """
    now = now or datetime.now()
    context = {
        "org_code": org_code or "",
        "now": now,
        "today": now.date(),
        "timedelta": timedelta,
        "date": date,
        "datetime": datetime,
    }
    for var in variables or []:
        if not isinstance(var, dict):
            continue
        name = str(var.get("name") or "").strip()
        if not name:
            continue
        value_type = str(var.get("value_type") or "string")
        raw_value = var.get("value")
        if value_type == "expression":
            value = _safe_eval(str(raw_value), context) if raw_value is not None else None
        else:
            value = _coerce_variable_value(raw_value, value_type)
        context[name] = value
    return context


def _coerce_variable_value(value: object, value_type: str):
    if value is None or value == "":
        return value
    if value_type == "string":
        return str(value)
    if value_type == "integer":
        return int(value)
    if value_type == "decimal":
        return float(value)
    if value_type == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "是")
        return bool(value)
    if value_type == "date":
        return str(value)
    if value_type == "json":
        return value
    return value


def merge_variables(*variable_groups: list | None) -> list[dict]:
    """按变量名合并，后面的定义覆盖前面的定义。"""
    merged: dict[str, dict] = {}
    for group in variable_groups:
        for var in group or []:
            if isinstance(var, dict) and var.get("name"):
                merged[str(var["name"])] = var
    return list(merged.values())


def render_request_params(
    value, org_code: str | None = None, variables: list[dict] | None = None, now: datetime | None = None
):
    """递归解析 ``{{ python_expression }}`` 参数占位符。"""
    context = build_variable_context(variables, org_code, now)
    if isinstance(value, dict):
        return {key: render_request_params(item, org_code, variables, now) for key, item in value.items()}
    if isinstance(value, list):
        return [render_request_params(item, org_code, variables, now) for item in value]
    if isinstance(value, str):
        return _render_string_expression(value, context)
    return value


def resolve_period_datetime(period_value: str | None) -> datetime | None:
    """期间值 → 取数时点：``2026`` → 1/1，``2026-09`` → 9/1，``2026-09-27`` → 当天。"""
    if not period_value:
        return None
    text = str(period_value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"期间值格式不支持: {period_value}（支持 YYYY / YYYY-MM / YYYY-MM-DD）")


_EXPR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def _render_string_expression(value: str, context: dict) -> object:
    matches = list(_EXPR_RE.finditer(value))
    if not matches:
        return value
    if len(matches) == 1 and matches[0].group(0) == value:
        return _safe_eval(matches[0].group(1), context)
    result = value
    for match in matches:
        result = result.replace(match.group(0), str(_safe_eval(match.group(1), context)))
    return result


def _safe_eval(expression: str, context: dict) -> object:
    """白名单节点 + 受限上下文的 Python 表达式求值。"""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"参数表达式语法错误: {expression}") from e

    allowed_nodes = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Attribute,
        ast.Call,
        ast.keyword,
        ast.Load,
        ast.Str,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Subscript,
        ast.Slice,
        ast.Tuple,
        ast.List,
        ast.Dict,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.IfExp,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"参数表达式包含不支持的语法: {ast.dump(node)}")

    allowed_names = set(context) | {"timedelta", "date", "datetime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(f"参数表达式包含不允许的变量: {node.id}")

    safe_builtins = {
        "__import__": __import__,
        "timedelta": timedelta,
        "date": date,
        "datetime": datetime,
    }
    try:
        return eval(compile(tree, "<param_expr>", "eval"), {"__builtins__": safe_builtins}, {**safe_builtins, **context})
    except Exception as e:
        raise ValueError(f"参数表达式执行失败: {expression}") from e


async def reconcile_meta_sync_jobs() -> None:
    """启动时把启用的同步任务恢复到 APScheduler。"""
    from sqlalchemy import false, select

    async with async_db_session() as db:
        jobs = (
            await db.execute(
                select(MetaSyncJobModel).where(
                    MetaSyncJobModel.is_deleted == false(),
                    MetaSyncJobModel.status == 0,
                )
            )
        ).scalars().all()
    for job in jobs:
        try:
            register_meta_sync_job(job)
        except Exception as e:
            logger.error(f"恢复元数据同步任务 {job.id} 失败: {e}")


async def _get_sys_report_data_with_retry(
    client: KingdeeClient, form_id: str, params: dict, retry_times: int = SYNC_RETRY_TIMES
) -> dict:
    """调用金蝶报表接口，网络类异常按退避重试（只读接口，重试安全）。"""
    last_error: Exception | None = None
    for attempt in range(max(1, retry_times)):
        try:
            return await client.get_sys_report_data(form_id, params)
        except Exception as e:  # noqa: BLE001 - 网络/SDK 异常统一重试
            last_error = e
            if attempt == max(1, retry_times) - 1:
                break
            delay = SYNC_RETRY_DELAY * (attempt + 1)
            logger.warning(f"金蝶报表 {form_id} 取数失败（第 {attempt + 1} 次），{delay}s 后重试: {e}")
            await asyncio.sleep(delay)
    raise RuntimeError(f"金蝶报表 {form_id} 取数失败: {last_error}") from last_error


async def fetch_report_data(
    client: KingdeeClient,
    form_id: str,
    base_params: dict,
    page_size: int = SYNC_PAGE_SIZE,
    max_pages: int = SYNC_MAX_PAGES,
) -> dict:
    """按 ``StartRow`` 翻页拉取金蝶报表全量数据。

    金蝶系统报表接口单次只返回 ``Limit`` 行；只取第一页会静默丢数据
    （科目余额表按科目顺序返回，6xxx 科目往往在 2000 行之后）。

    参数:
    - client (KingdeeClient): 金蝶客户端。
    - form_id (str): 报表 FormId，如 ``GL_RPT_AccountBalance``。
    - base_params (dict): 已渲染好变量的请求参数，其中 StartRow/Limit 会被逐页覆盖。
    - page_size (int): 每页行数。
    - max_pages (int): 最大翻页数，防止异常情况下无限循环。

    返回:
    - dict: 合并后的报表结果，``Rows`` 为全量行，``RowCount`` 为实际取回行数。
    """
    merged: list = []
    report: dict = {}
    start = 0
    for _ in range(max_pages):
        page_params = {**base_params, "StartRow": start, "Limit": page_size}
        response = await _get_sys_report_data_with_retry(client, form_id, page_params)
        page_report = response.get("Result") or {}
        if not report:
            report = dict(page_report)
        page_rows = page_report.get("Rows")
        page_rows = page_rows if isinstance(page_rows, list) else []
        merged.extend(page_rows)
        if len(page_rows) < page_size:
            break
        start += len(page_rows)
    report["Rows"] = merged
    report["RowCount"] = len(merged)
    return report


KINGDEE_CONNECTOR = "kingdee"
JUSHUITAN_CONNECTOR = "jushuitan"
CRM_CONNECTOR = "crm"
# 金蝶单据查询（ExecuteBillQuery）：来源对象 ``query_type = bill_query``
KINGDEE_QUERY_TYPE_BILL = "bill_query"


async def fetch_kingdee_bill_query(
    client: KingdeeClient,
    form_id: str,
    base_params: dict,
    page_size: int = SYNC_PAGE_SIZE,
    max_pages: int = SYNC_MAX_PAGES,
) -> dict:
    """按 ``ExecuteBillQuery`` 分页拉取金蝶单据全量数据（与报表同构，返回 ``Rows``）。

    请求参数取自来源对象/同步任务的 ``request_params``（已渲染变量）：
    ``FieldKeys`` / ``FilterString`` / ``OrderString`` / ``TopRowCount``；
    ``StartRow`` 与 ``Limit`` 由本函数逐页覆盖，避免只取第一页静默丢数据。
    """
    merged: list = []
    field_keys = str(base_params.get("FieldKeys") or "")
    filter_string = str(base_params.get("FilterString") or "")
    order_string = str(base_params.get("OrderString") or "")
    top_row_count = int(base_params.get("TopRowCount") or 0)
    start = 0
    for _ in range(max_pages):
        _fields, items = await client.bill_query(
            KingdeeBillQueryRequest(
                form_id=form_id,
                field_keys=field_keys,
                filter_string=filter_string,
                order_string=order_string,
                top_row_count=top_row_count,
                start_row=start,
                limit=page_size,
            )
        )
        merged.extend(items)
        if len(items) < page_size:
            break
        start += len(items)
    return {"Rows": merged, "RowCount": len(merged)}


async def fetch_crm_amount_payload(connection_id: int, path: str, params: dict) -> dict:
    """CRM 接口取数，返回原始响应（含 ``data``），并补一个 ``data_count``。

    CRM 全部为 GET 接口、无需鉴权；``path`` 取自来源对象 ``code``（如
    ``/hs/order/getDtAmount``），参数由同步任务模板渲染——``dateRange`` 走
    ``dateRange[]``，其余键（如报价统计的 ``transformation``）原样透传；
    **列表值参数**（如 ``pushDateRange`` / ``createDateRange``）由客户端统一补
    ``[]``（CRM 是 PHP 应用，重复键不加 ``[]`` 只会保留最后一个值，区间会退化成单点）。
    """
    async with async_db_session() as db:
        connection = await db.get(CrmConnectionModel, connection_id)
    if connection is None:
        raise RuntimeError("CRM 连接配置不存在")
    params = params if isinstance(params, dict) else {}
    raw = params.get("dateRange") if isinstance(params, dict) else None
    if isinstance(raw, str):
        date_range: list[str] | None = [item.strip() for item in raw.replace("~", ",").split(",") if item.strip()]
    elif isinstance(raw, (list, tuple)):
        date_range = [str(item) for item in raw if item]
    else:
        date_range = None
    extra_params = {key: value for key, value in params.items() if key != "dateRange"}
    async with build_crm_client(connection) as client:
        payload = await client.call(path, date_range, extra_params)
    result = dict(payload) if isinstance(payload, dict) else {}
    # 明细接口（orderAnalyze / orderShipments）``data`` 是数组，行数按数组长度登记；
    # 单值接口（金额/比率）仍按 1 行登记，保持原有语义。
    data = result.get("data")
    result["data_count"] = len(data) if isinstance(data, list) else 1
    return result


async def fetch_jushuitan_sales_outbound(connection_id: int, biz: dict) -> dict:
    """聚水潭销售出库取数，返回与金蝶报表同构的 ``{"datas": [...]}`` 结构。

    ``biz`` 由同步任务的 ``request_params`` 渲染而来，必须包含
    ``modified_begin``/``modified_end``（``yyyy-MM-dd HH:mm:ss``）；超过 7 天由客户端自动分段。
    """
    async with async_db_session() as db:
        connection = await db.get(JushuitanConnectionModel, connection_id)
    if connection is None:
        raise RuntimeError("聚水潭连接配置不存在")
    rows = await fetch_sales_outbound_rows(connection, biz)
    return {"datas": rows, "data_count": len(rows)}


async def fetch_source_payload(source_system: SourceSystemModel, source_object: SourceObjectModel, params: dict) -> dict:
    """按来源系统的 ``connector_type`` 分派取数，统一返回 ``{"Rows"|"datas": [...]}``。"""
    connector_type = str(getattr(source_system, "connector_type", "") or KINGDEE_CONNECTOR).strip().lower()
    if connector_type == JUSHUITAN_CONNECTOR:
        return await fetch_jushuitan_sales_outbound(int(source_system.connection_id or 0), params)
    if connector_type == CRM_CONNECTOR:
        return await fetch_crm_amount_payload(int(source_system.connection_id or 0), source_object.code, params)
    async with async_db_session() as db:
        connection = await db.get(KingdeeConnectionModel, source_system.connection_id)
    if connection is None:
        raise RuntimeError("金蝶连接配置不存在")
    client = KingdeeService._client_from(connection)
    if str(source_object.query_type or "").strip() == KINGDEE_QUERY_TYPE_BILL:
        # 单据查询：一次取一页，按 StartRow 翻页
        return await fetch_kingdee_bill_query(client, source_object.code, params)
    return await fetch_report_data(client, source_object.code, params)


def extract_payload_rows(payload: dict) -> list:
    """兼容金蝶 ``Rows``、聚水潭 ``datas`` 与 CRM ``data``（明细数组）三种返回结构。"""
    for key in ("Rows", "datas"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    # CRM 明细接口（orderAnalyze / orderShipments）把明细数组放在 ``data`` 里
    data = payload.get("data")
    if isinstance(data, list):
        return data
    return []


async def execute_meta_sync_job(job_id: int, period_value: str | None = None) -> None:
    """执行一次元数据同步任务，并把运行日志和原始返回落库。

    参数:
    - job_id (int): 同步任务ID。
    - period_value (str | None): 取数期间（``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD``）。
      缺省按当前时间渲染模板；指定后 ``{{year}}``/``{{month}}`` 等变量会按该期间渲染，
      用于历史期间回补，批次也会记录该期间。
    """
    batch_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    run_id: int | None = None
    run_now = resolve_period_datetime(period_value)
    try:
        async with async_db_session() as db, db.begin():
            job = await db.get(MetaSyncJobModel, job_id)
            if job is None or job.status == 1:
                return
            run = MetaSyncRunModel(
                job_id=job_id,
                batch_id=batch_id,
                period_value=period_value or datetime.now().strftime("%Y-%m"),
                status="running",
                started_at=datetime.now(UTC),
            )
            db.add(run)
            await db.flush()
            run_id = run.id
            source_object = await db.get(SourceObjectModel, job.source_object_id)
            source_system = await db.get(SourceSystemModel, job.source_system_id)
            variables = merge_variables(source_object.variables if source_object else None, job.variables)
            request_params = render_request_params(job.request_params or {}, job.org_code, variables, now=run_now)

        if source_object is None or source_system is None or source_system.connection_id is None:
            raise RuntimeError("同步任务缺少来源对象或连接配置")

        report = await fetch_source_payload(source_system, source_object, request_params)
        rows = extract_payload_rows(report)
        row_count = int(report.get("RowCount") or report.get("data_count") or len(rows))

        async with async_db_session() as db, db.begin():
            run = await db.get(MetaSyncRunModel, run_id)
            if run is not None:
                run.status = "success"
                run.row_count = row_count
                run.rows_json = report
                run.finished_at = datetime.now(UTC)
        logger.info(f"元数据同步任务 {job_id} 执行成功，批次 {batch_id}，行数 {row_count}")
    except Exception as e:
        logger.exception(f"元数据同步任务 {job_id} 执行失败")
        if run_id is not None:
            async with async_db_session() as db, db.begin():
                run = await db.get(MetaSyncRunModel, run_id)
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)[:4000]
                    run.finished_at = datetime.now(UTC)
