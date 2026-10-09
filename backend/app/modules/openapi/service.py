"""开放接口服务：应用管理（管理端）与指标读取（对外开放）。"""

import re
from datetime import date
from typing import Any

from redis.asyncio.client import Redis
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.modules.masterdata.model import MasterOrgModel
from app.modules.metric.engine import current_period_value, execute_metric_calc
from app.modules.metric.model import MetricDefModel, MetricValueModel
from app.modules.metric.units import resolve_metric_unit
from app.modules.openapi.crud import OpenApiLogCRUD, OpenClientCRUD
from app.modules.openapi.model import OpenClientModel
from app.modules.openapi.schema import (
    OpenApiLogOutSchema,
    OpenApiLogQueryParam,
    OpenClientCreateResultSchema,
    OpenClientCreateSchema,
    OpenClientOutSchema,
    OpenClientQueryParam,
    OpenClientUpdateSchema,
    OpenMetricErrorSchema,
    OpenMetricOutSchema,
    OpenMetricQuerySchema,
    OpenMetricValueItemSchema,
)
from app.modules.openapi.security import (
    CODE_METRIC_FORBIDDEN,
    CODE_PARAM_INVALID,
    generate_app_secret,
    hash_app_secret,
    revoke_tokens,
)
from app.utils.common_util import search_to_dict

_PERIOD_PATTERNS: dict[str, re.Pattern] = {
    "day": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "week": re.compile(r"^\d{4}-W\d{2}$"),
    "month": re.compile(r"^\d{4}-\d{2}$"),
    "year": re.compile(r"^\d{4}$"),
}

# 单次请求允许的最大期间跨度：避免外部系统一次拉全量历史把库拖垮
_PERIOD_MAX_SPAN: dict[str, int] = {"day": 366, "week": 104, "month": 36, "year": 10}

def _to_float(value: Any) -> float:
    """Numeric → float，统一保留 4 位小数（与 metric_value 精度一致）。"""
    if value is None:
        return 0.0
    return round(float(value), 4)


def _period_to_index(period_type: str, value: str) -> int:
    """把期间值折算成可比较的序号，用于统计跨度和排序校验。"""
    if period_type == "day":
        return date.fromisoformat(value).toordinal()
    if period_type == "week":
        year, week = value.split("-W")
        return date.fromisocalendar(int(year), int(week), 1).toordinal()
    if period_type == "year":
        return int(value)
    year, month = value.split("-")
    return int(year) * 12 + int(month)


def _resolve_period_range(period_type: str, start: str | None, end: str | None) -> tuple[str, str]:
    """校验并归一期间区间，缺省取当前期间。"""
    pattern = _PERIOD_PATTERNS.get(period_type)
    if pattern is None:
        raise CustomException(msg=f"不支持的期间类型：{period_type}", code=CODE_PARAM_INVALID, status_code=400)

    current = current_period_value(period_type)
    start = (start or end or current).strip()
    end = (end or start).strip()
    for value in (start, end):
        if not pattern.match(value):
            raise CustomException(
                msg=f"期间格式非法：{value}（{period_type} 期望 {pattern.pattern}）",
                code=CODE_PARAM_INVALID,
                status_code=400,
            )
    try:
        span = _period_to_index(period_type, end) - _period_to_index(period_type, start) + 1
    except ValueError as e:
        raise CustomException(msg=f"期间值非法：{start} ~ {end}", code=CODE_PARAM_INVALID, status_code=400) from e
    if span <= 0:
        raise CustomException(msg="period_end 不能早于 period_start", code=CODE_PARAM_INVALID, status_code=400)
    if span > _PERIOD_MAX_SPAN[period_type]:
        raise CustomException(
            msg=f"期间跨度超限：{period_type} 单次最多 {_PERIOD_MAX_SPAN[period_type]} 个期间",
            code=CODE_PARAM_INVALID,
            status_code=400,
        )
    return start, end


def _to_create_result(obj: Any, secret: str) -> OpenClientCreateResultSchema:
    """应用 ORM 对象 → 含明文密钥的返回体（密钥只在创建/重置时出现一次）。"""
    return OpenClientCreateResultSchema(**OpenClientOutSchema.model_validate(obj).model_dump(), app_secret=secret)


class OpenClientService:
    """管理端：接入应用配置。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def page(
        self, search: OpenClientQueryParam | None, page_no: int, page_size: int
    ) -> PageResultSchema[OpenClientOutSchema]:
        result = await OpenClientCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"id": "desc"}],
            search=search_to_dict(search),
            out_schema=OpenClientOutSchema,
        )
        return result

    async def detail(self, id: int) -> OpenClientOutSchema:
        return await OpenClientCRUD(self.auth, self.db).get_or_404(
            id=id, msg="该应用不存在", out_schema=OpenClientOutSchema
        )

    async def create(self, data: OpenClientCreateSchema) -> OpenClientCreateResultSchema:
        crud = OpenClientCRUD(self.auth, self.db)
        if await crud.get(app_id=data.app_id):
            raise CustomException(msg="创建失败，应用标识已存在")
        secret = generate_app_secret()
        obj = await crud.create(data={"app_id": data.app_id, "secret_hash": await hash_app_secret(secret), **data.model_dump(exclude={"app_id"})})
        return _to_create_result(obj, secret)

    async def update(self, id: int, data: OpenClientUpdateSchema, redis: Redis) -> OpenClientOutSchema:
        crud = OpenClientCRUD(self.auth, self.db)
        obj = await crud.get_or_404(id=id, msg="更新失败，该应用不存在")
        # exclude_unset（而非 exclude_none）：前端清空 IP 白名单 / 到期时间时要能真正置空
        payload = data.model_dump(exclude_unset=True)
        for key in ("ip_whitelist", "contact", "description"):
            value = payload.get(key)
            if isinstance(value, str) and not value.strip():
                payload[key] = None
        await crud.update(id=id, data=payload)
        # 停用应用时立即失效其已签发令牌，避免「已停用仍能调用」的窗口期
        if payload.get("status") == 1:
            await revoke_tokens(redis, obj.app_id)
        return await self.detail(id)

    async def delete(self, ids: list[int], redis: Redis) -> None:
        crud = OpenClientCRUD(self.auth, self.db)
        for id in ids:
            obj = await crud.get(id=id)
            if obj is not None:
                await revoke_tokens(redis, obj.app_id)
        await crud.delete(ids=ids)

    async def reset_secret(self, id: int, redis: Redis) -> OpenClientCreateResultSchema:
        """重置密钥：旧密钥与旧令牌同时失效。"""
        crud = OpenClientCRUD(self.auth, self.db)
        obj = await crud.get_or_404(id=id, msg="该应用不存在")
        secret = generate_app_secret()
        await crud.update(id=id, data={"secret_hash": await hash_app_secret(secret)})
        await revoke_tokens(redis, obj.app_id)
        refreshed = await crud.get_or_404(id=id, msg="该应用不存在")
        return _to_create_result(refreshed, secret)

    async def org_options(self) -> list[dict[str, str]]:
        """组织下拉选项：``value`` 用组织编码，与 ``org_scope`` 存储口径一致。"""
        rows = (
            (
                await self.db.execute(
                    select(MasterOrgModel)
                    .where(MasterOrgModel.status == 0, MasterOrgModel.is_deleted == False)  # noqa: E712
                    .order_by(MasterOrgModel.code.asc())
                )
            )
            .scalars()
            .all()
        )
        return [{"value": row.code, "label": f"{row.code} - {row.name}"} for row in rows]


class OpenApiLogService:
    """管理端：开放接口调用日志查询。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def page(
        self, search: OpenApiLogQueryParam | None, page_no: int, page_size: int
    ) -> PageResultSchema[OpenApiLogOutSchema]:
        return await OpenApiLogCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"id": "desc"}],
            search=search_to_dict(search),
            out_schema=OpenApiLogOutSchema,
        )


class OpenApiService:
    """对外开放：指标目录、批量取数、组织字典、触发重算。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── 指标目录 ────────────────────────────────────────────────────
    async def page_metrics(
        self, keyword: str | None, page_no: int, page_size: int
    ) -> dict[str, Any]:
        conditions = [MetricDefModel.status == 0, MetricDefModel.is_deleted == False]  # noqa: E712
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(MetricDefModel.code.like(like) | MetricDefModel.name.like(like))

        total = (
            await self.db.execute(select(func.count(MetricDefModel.id)).where(*conditions))
        ).scalar() or 0
        rows = (
            (
                await self.db.execute(
                    select(MetricDefModel)
                    .where(*conditions)
                    .order_by(MetricDefModel.code.asc())
                    .offset((page_no - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        items = [self._metric_meta(metric) for metric in rows]
        return {
            "page_no": page_no,
            "page_size": page_size,
            "total": total,
            "has_next": page_no * page_size < total,
            "items": items,
        }

    @staticmethod
    def _metric_meta(metric: MetricDefModel) -> dict[str, Any]:
        dimensions = metric.dimensions or {}
        dim_names = list(dimensions.keys()) if isinstance(dimensions, dict) else []
        return OpenMetricOutSchema(
            code=metric.code,
            name=metric.name,
            excel_code=metric.excel_code,
            period_type=metric.period_type,
            unit=resolve_metric_unit(metric.name, metric.measures),
            dimensions=dim_names,
            description=metric.description,
        ).model_dump()

    async def _load_metrics(self, codes: list[str]) -> tuple[list[MetricDefModel], list[dict]]:
        """按标识加载启用指标。

        入参既可传系统指标编码（``marketing_office_expense``），也可传 Excel 科目编码
        （``EXP-01-a``）——外部财务系统常按 Excel 编码对账，两种写法都能命中同一指标；
        不存在或停用的标识逐条记录原因，不静默丢弃。
        """
        wanted = [code.strip() for code in codes if code and code.strip()]
        rows = (
            (
                await self.db.execute(
                    select(MetricDefModel).where(
                        MetricDefModel.code.in_(wanted) | MetricDefModel.excel_code.in_(wanted),
                        MetricDefModel.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        by_code = {metric.code: metric for metric in rows}
        by_excel_code = {metric.excel_code: metric for metric in rows if metric.excel_code}
        metrics: list[MetricDefModel] = []
        errors: list[dict] = []
        seen: set[int] = set()
        for token in wanted:
            metric = by_code.get(token) or by_excel_code.get(token)
            if metric is not None and metric.id in seen:
                continue  # 同一指标被编码与 Excel 编码重复请求，只取一次
            if metric is None:
                errors.append(OpenMetricErrorSchema(metric_code=token, reason="指标不存在").model_dump())
            elif int(metric.status or 0) != 0:
                errors.append(OpenMetricErrorSchema(metric_code=token, reason="指标已停用").model_dump())
            else:
                seen.add(metric.id)
                metrics.append(metric)
        return metrics, errors

    # ── 组织字典 ────────────────────────────────────────────────────
    async def _load_orgs(self, client: OpenClientModel) -> list[MasterOrgModel]:
        """加载该应用可见的组织（停用/已删除的不返回）。"""
        rows = (
            (
                await self.db.execute(
                    select(MasterOrgModel)
                    .where(MasterOrgModel.status == 0, MasterOrgModel.is_deleted == False)  # noqa: E712
                    .order_by(MasterOrgModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
        allowed = {str(code) for code in (client.org_scope or []) if str(code).strip()}
        if allowed:
            rows = [row for row in rows if row.code in allowed]
        return list(rows)

    async def list_orgs(self, client: OpenClientModel) -> list[dict[str, Any]]:
        rows = await self._load_orgs(client)
        code_by_id = {row.id: row.code for row in rows}
        depth_cache: dict[int, int] = {}

        def depth_of(org: MasterOrgModel, seen: set[int] | None = None) -> int:
            if org.id in depth_cache:
                return depth_cache[org.id]
            seen = seen or set()
            if org.parent_id is None or org.parent_id in seen or org.parent_id not in code_by_id:
                depth_cache[org.id] = 1
                return 1
            parent = next((row for row in rows if row.id == org.parent_id), None)
            depth = 1 if parent is None else depth_of(parent, seen | {org.id}) + 1
            depth_cache[org.id] = depth
            return depth

        return [
            {
                "org_code": row.code,
                "org_name": row.name,
                "parent_code": code_by_id.get(row.parent_id) if row.parent_id else None,
                "level": depth_of(row),
            }
            for row in rows
        ]

    # ── 批量取数 ────────────────────────────────────────────────────
    async def query_metrics(self, client: OpenClientModel, payload: OpenMetricQuerySchema) -> dict[str, Any]:
        if payload.level in ("dept", "all") and not client.allow_dept_detail:
            raise CustomException(
                msg="该应用仅开放组织合计，level 不能为 dept/all",
                code=CODE_METRIC_FORBIDDEN,
                status_code=403,
            )
        if payload.level == "person" and not client.allow_person_detail:
            raise CustomException(
                msg="该应用未开放业务员明细，level 不能为 person",
                code=CODE_METRIC_FORBIDDEN,
                status_code=403,
            )

        metrics, errors = await self._load_metrics(payload.metrics)
        if not metrics:
            raise CustomException(
                msg="请求的指标均不可读：" + "；".join(f"{e['metric_code']}({e['reason']})" for e in errors),
                code=CODE_METRIC_FORBIDDEN,
                status_code=403,
            )

        period_type = payload.period_type
        period_start, period_end = _resolve_period_range(period_type, payload.period_start, payload.period_end)
        orgs = await self._load_orgs(client)
        org_code_by_id = {row.id: row.code for row in orgs}
        org_name_by_code = {row.code: row.name for row in orgs}
        allowed_codes = {row.code for row in orgs}
        restricted = False
        if payload.org_codes:
            requested = {str(code).strip() for code in payload.org_codes if str(code).strip()}
            denied = sorted(requested - allowed_codes)
            if denied:
                raise CustomException(
                    msg="组织不在授权范围内：" + "、".join(denied),
                    code=CODE_METRIC_FORBIDDEN,
                    status_code=403,
                )
            allowed_codes = requested
            restricted = True
        elif client.org_scope:
            restricted = True

        items = await self._fetch_values(
            metrics=metrics,
            org_code_by_id=org_code_by_id,
            org_name_by_code=org_name_by_code,
            allowed_codes=allowed_codes,
            restricted=restricted,
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            level=payload.level,
            person_codes=payload.person_codes,
            person_ids=payload.person_ids,
            total_only=payload.total_only,
        )
        metric_name_by_code = {metric.code: metric.name for metric in metrics}
        if payload.include_meta:
            for item in items:
                item["metric_name"] = metric_name_by_code.get(item["metric_code"])

        result: dict[str, Any] = {
            "period_type": period_type,
            "period_start": period_start,
            "period_end": period_end,
            "level": payload.level,
            "total_only": payload.total_only,
            "calc_version_policy": "latest",
            "metrics": [OpenMetricOutSchema(**self._metric_meta(metric)).model_dump() for metric in metrics]
            if payload.include_meta
            else [],
            "errors": errors,
        }
        if payload.total_only:
            # 只给合计：不返回组织明细，按「指标 × 期间」汇总，便于外部系统直接取一个数
            result["totals"] = self._to_totals(items)
            result["items"] = []
            result["summary"] = self._summary(items, metrics, period_start, period_end, payload.level)
        elif payload.format == "wide":
            result["columns"] = [
                "period_value",
                "org_code",
                "org_name",
                "dept_code",
                "dept_name",
                "person_id",
                "person_code",
                "person_name",
                *[metric.code for metric in metrics],
            ]
            result["rows"] = self._to_wide(items, metrics)
            result["summary"] = self._summary(items, metrics, period_start, period_end, payload.level)
        else:
            result["items"] = items
            result["summary"] = self._summary(items, metrics, period_start, period_end, payload.level)
        return result

    @staticmethod
    def _to_totals(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按「指标 × 期间」汇总为合计行（跨组织/核算维度求和）。"""
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for item in items:
            key = (item["metric_code"], item["period_value"])
            row = buckets.get(key)
            if row is None:
                row = {
                    "metric_code": item["metric_code"],
                    "metric_name": item.get("metric_name"),
                    "excel_code": item.get("excel_code"),
                    "period_value": item["period_value"],
                    "value": 0.0,
                    "_orgs": set(),
                    "calc_version": item.get("calc_version"),
                    "calc_time": item.get("calc_time"),
                }
                buckets[key] = row
            row["value"] = round(row["value"] + item["value"], 4)
            row["_orgs"].add(item.get("org_code"))
            calc_time = item.get("calc_time")
            if calc_time is not None:
                if row.get("calc_time") is None:
                    row["calc_time"] = calc_time
                else:
                    try:
                        if calc_time > row["calc_time"]:
                            row["calc_time"] = calc_time
                    except TypeError:  # 时区感知与朴素时间混用时不比较，保留先到的值
                        pass

        totals: list[dict[str, Any]] = []
        for row in sorted(buckets.values(), key=lambda r: (r["period_value"], r["metric_code"])):
            row["org_count"] = len([code for code in row.pop("_orgs") if code])
            totals.append(row)
        return totals

    async def _fetch_values(
        self,
        metrics: list[MetricDefModel],
        org_code_by_id: dict[int, str],
        org_name_by_code: dict[str, str],
        allowed_codes: set[str],
        restricted: bool,
        period_type: str,
        period_start: str,
        period_end: str,
        level: str,
        person_codes: list[str] | None = None,
        person_ids: list[int] | None = None,
        total_only: bool = False,
    ) -> list[dict[str, Any]]:
        """按「指标 × 期间 × 组织（× 维度）」取最新计算版本的结果行。"""
        metric_ids = [metric.id for metric in metrics]
        base_conditions = [
            MetricValueModel.metric_id.in_(metric_ids),
            MetricValueModel.period_type == period_type,
            MetricValueModel.period_value >= period_start,
            MetricValueModel.period_value <= period_end,
            MetricValueModel.is_deleted == False,  # noqa: E712
        ]
        if level == "org":
            # 组织合计层：既没有核算维度、也没有业务员
            base_conditions.append(MetricValueModel.dept_code.is_(None))
            base_conditions.append(MetricValueModel.person_code.is_(None))
        elif level == "dept":
            base_conditions.append(MetricValueModel.dept_code.is_not(None))
            base_conditions.append(MetricValueModel.person_code.is_(None))
        elif level == "person":
            if total_only:
                # 「只要合计」时取公司合计层：业务员行是明细，直接相加会把
                # 平均值（下推周期）与去重计数（老客户数）算错
                base_conditions.append(MetricValueModel.dept_code.is_(None))
                base_conditions.append(MetricValueModel.person_code.is_(None))
            else:
                base_conditions.append(MetricValueModel.person_code.is_not(None))
        if person_codes:
            wanted = [str(code).strip() for code in person_codes if str(code).strip()]
            if wanted:
                base_conditions.append(MetricValueModel.person_code.in_(wanted))
        if person_ids:
            wanted_ids = [int(item) for item in person_ids if item]
            if wanted_ids:
                base_conditions.append(MetricValueModel.person_id.in_(wanted_ids))

        # 每个指标 + 期间的最新计算版本（全量重算递增版本，单组织重算沿用版本，
        # 因此同一版本内已包含全部组织，取版本的最大值即可）
        latest = (
            select(
                MetricValueModel.metric_id.label("metric_id"),
                MetricValueModel.period_value.label("period_value"),
                func.max(MetricValueModel.calc_version).label("calc_version"),
            )
            .where(*base_conditions)
            .group_by(MetricValueModel.metric_id, MetricValueModel.period_value)
            .subquery()
        )
        rows = (
            (
                await self.db.execute(
                    select(MetricValueModel)
                    .join(
                        latest,
                        and_(
                            MetricValueModel.metric_id == latest.c.metric_id,
                            MetricValueModel.period_value == latest.c.period_value,
                            MetricValueModel.calc_version == latest.c.calc_version,
                        ),
                    )
                    .where(*base_conditions)
                    .order_by(
                        MetricValueModel.period_value.asc(),
                        MetricValueModel.org_id.asc(),
                        MetricValueModel.metric_id.asc(),
                        MetricValueModel.dept_code.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        code_by_metric_id = {metric.id: metric.code for metric in metrics}
        excel_code_by_metric_id = {metric.id: metric.excel_code for metric in metrics}
        items: list[dict[str, Any]] = []
        for row in rows:
            org_code = org_code_by_id.get(row.org_id) if row.org_id else None
            if org_code is not None and org_code not in allowed_codes:
                continue
            if org_code is None and row.org_id is not None:
                # 组织已停用或不在授权范围内
                continue
            if org_code is None and restricted:
                # 未映射到标准组织的行判定不了归属，授权受限时不外发
                continue
            items.append(
                OpenMetricValueItemSchema(
                    metric_code=code_by_metric_id.get(row.metric_id, ""),
                    excel_code=excel_code_by_metric_id.get(row.metric_id),
                    period_value=row.period_value,
                    org_code=org_code,
                    org_name=org_name_by_code.get(org_code) if org_code else None,
                    dept_code=row.dept_code,
                    dept_name=row.dept_name,
                    person_id=row.person_id,
                    person_code=row.person_code,
                    person_name=row.person_name,
                    value=_to_float(row.value),
                    calc_version=row.calc_version,
                    calc_time=row.calc_time,
                    batch_id=row.batch_id,
                ).model_dump()
            )
        return items

    @staticmethod
    def _summary(
        items: list[dict[str, Any]],
        metrics: list[MetricDefModel],
        period_start: str,
        period_end: str,
        level: str = "org",
    ) -> dict[str, Any]:
        # 合计口径：优先取「组织合计层」行；按业务员取数时没有合计层，退化为业务员行求和
        total_rows = [
            item for item in items if not item.get("dept_code") and not item.get("person_code")
        ]
        if not total_rows and level == "person":
            total_rows = items
        return {
            "metric_count": len(metrics),
            "item_count": len(items),
            "period_start": period_start,
            "period_end": period_end,
            "period_count": len({item["period_value"] for item in items}),
            "org_count": len({item["org_code"] for item in items if item["org_code"]}),
            "person_count": len({item.get("person_code") for item in items if item.get("person_code")}),
            "total": _to_float(sum(item["value"] for item in total_rows)),
        }

    @staticmethod
    def _to_wide(items: list[dict[str, Any]], metrics: list[MetricDefModel]) -> list[dict[str, Any]]:
        """宽表：一行一个「期间 × 组织（× 维度）」，指标编码变成列。"""
        rows: dict[tuple, dict[str, Any]] = {}
        for item in items:
            key = (
                item["period_value"],
                item["org_code"],
                item["dept_code"],
                item.get("person_id"),
                item.get("person_code"),
            )
            row = rows.setdefault(
                key,
                {
                    "period_value": item["period_value"],
                    "org_code": item["org_code"],
                    "org_name": item["org_name"],
                    "dept_code": item["dept_code"],
                    "dept_name": item["dept_name"],
                    "person_id": item.get("person_id"),
                    "person_code": item.get("person_code"),
                    "person_name": item.get("person_name"),
                },
            )
            row[item["metric_code"]] = item["value"]
        for row in rows.values():
            for metric in metrics:
                row.setdefault(metric.code, None)
        return list(rows.values())

    # ── 触发重算 ────────────────────────────────────────────────────
    async def run_metric(self, client: OpenClientModel, code: str, period_value: str | None) -> dict[str, Any]:
        if not client.allow_run_calc:
            raise CustomException(
                msg="该应用未开放重算权限，请联系管理员",
                code=CODE_METRIC_FORBIDDEN,
                status_code=403,
            )
        metric = (
            await self.db.execute(
                select(MetricDefModel).where(
                    MetricDefModel.code == code.strip(),
                    MetricDefModel.status == 0,
                    MetricDefModel.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().first()
        if metric is None:
            raise CustomException(msg=f"指标不存在或已停用：{code}", code=CODE_PARAM_INVALID, status_code=400)
        try:
            summary = await execute_metric_calc(metric_id=metric.id, period_value=period_value)
        except ValueError as e:
            raise CustomException(msg=str(e), code=CODE_PARAM_INVALID, status_code=400) from e
        return {
            "metric_code": summary.get("metric_code", metric.code),
            "period_type": summary.get("period_type", metric.period_type),
            "period_value": summary.get("period_value"),
            "calc_version": summary.get("calc_version", 1),
            "total": _to_float(summary.get("total")),
            "org_count": summary.get("org_count", 0),
        }
