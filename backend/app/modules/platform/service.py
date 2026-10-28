"""平台分析取数：基础量从零售订单/售后/店铺实时汇总，指标值按配置表达式计算。

- 基础量（orders / intake / shipment / ...）是代码里唯一的取数逻辑；
- 指标（PLT-xx）存放在 ``platform_metric_def``，用表达式描述，增删改不需要改代码；
- 输出按字段编码组织，前端与产品线分析一样按字段编码渲染列。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CustomException
from app.modules.openapi.security import CODE_PARAM_INVALID
from app.modules.retail.model import RetailOrderModel, RetailShopModel
from app.modules.retail.query_service import (
    RetailQueryService,
    hq_allocation_rate,
    retail_tax_rate,
    settlement_rate,
)

from .defaults import BASE_VARIABLES, DEFAULT_METRICS
from .expression import ExpressionError, evaluate
from .model import PlatformMetricModel
from .schema import PlatformAnalysisQueryParam, PlatformMetricUpsertParam

BASE_SUM_KEYS = (
    "orders",
    "shipped_orders",
    "cancelled_orders",
    "intake",
    "shipment",
    "cancelled_amount",
    "refund",
)
DIM_KEYS = {
    "period": "period",
    "platform": "platform",
    "shop_name": "shop_name",
    "shop_id": "shop_id",
}

PLATFORM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("天猫", ("天猫", "淘宝")),
    ("京东", ("京东",)),
    ("拼多多", ("拼多多", "多多")),
    ("抖音", ("抖音", "抖店")),
    ("小红书", ("小红书",)),
    ("1688", ("1688", "阿里巴巴")),
)


def normalize_platform(raw: str | None) -> str:
    """把 ``retail_shop.shop_site`` 归一成平台大类。"""
    text = (raw or "").strip()
    if not text:
        return "其他"
    for name, keywords in PLATFORM_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return name
    return "其他"


def _rate_vars() -> dict[str, float]:
    return {
        "tax_rate": retail_tax_rate(),
        "settlement_rate": settlement_rate() / 100,
        "hq_rate": hq_allocation_rate() / 100,
    }


def _field_row(metric: PlatformMetricModel) -> dict[str, Any]:
    return {
        "field_code": metric.code,
        "field_name": metric.name,
        "data_type": metric.data_type,
        "group": metric.group,
        "sensitive": bool(metric.sensitive),
        "note": metric.note,
        "unit": metric.unit,
        "expression": metric.expression,
        "status": "ready" if metric.status == 0 else "disabled",
        "status_label": "现用可出" if metric.status == 0 else "已停用",
        "stored_in": "platform_metric_def",
    }


class PlatformAnalysisService:
    """平台分析（指标中心 → 平台分析）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── 指标配置 ──────────────────────────────────────────────
    async def configs(self, only_enabled: bool = True) -> list[PlatformMetricModel]:
        conditions = [PlatformMetricModel.is_deleted == False]  # noqa: E712
        if only_enabled:
            conditions.append(PlatformMetricModel.status == 0)
        rows = (
            await self.db.execute(
                select(PlatformMetricModel)
                .where(*conditions)
                .order_by(PlatformMetricModel.sort.asc(), PlatformMetricModel.id.asc())
            )
        ).scalars().all()
        if not rows and only_enabled:
            # 表还没初始化时不至于白屏：用代码里的默认定义兜底（只读）
            return [
                PlatformMetricModel(
                    code=item["code"],
                    name=item["name"],
                    group=item["group"],
                    data_type=item["data_type"],
                    unit=item.get("unit"),
                    sensitive=bool(item.get("sensitive")),
                    expression=item["expression"],
                    note=item.get("note"),
                    sort=item["sort"],
                    status=0,
                )
                for item in DEFAULT_METRICS
            ]
        return list(rows)

    async def fields(self) -> list[dict[str, Any]]:
        return [_field_row(metric) for metric in await self.configs()]

    async def list_metrics(self) -> dict[str, Any]:
        metrics = await self.configs(only_enabled=False)
        return {
            "items": [_field_row(metric) | {"id": metric.id, "status_num": metric.status,
                                            "sort": metric.sort} for metric in metrics],
            "base_variables": BASE_VARIABLES,
            "functions": ["abs(x)", "round(x, n)", "min(a, b)", "max(a, b)", "choose(cond, a, b)"],
        }

    async def upsert_metric(self, data: PlatformMetricUpsertParam, metric_id: int | None = None) -> dict[str, Any]:
        code = data.code.strip().upper()
        existing = (
            await self.db.execute(
                select(PlatformMetricModel).where(
                    PlatformMetricModel.code == code,
                    PlatformMetricModel.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().first()
        if existing is not None and (metric_id is None or existing.id != metric_id):
            raise CustomException(msg=f"指标编码已存在：{code}", code=CODE_PARAM_INVALID, status_code=400)
        if data.data_type != "string":
            self._validate_expression(data.expression, code)
        payload = {
            "code": code,
            "name": data.name.strip(),
            "group": data.group.strip() or "金额",
            "data_type": data.data_type,
            "unit": data.unit,
            "sensitive": data.sensitive,
            "expression": data.expression.strip(),
            "note": data.note,
            "sort": data.sort,
            "status": data.status,
        }
        if metric_id is not None:
            target = await self.db.get(PlatformMetricModel, metric_id)
            if target is None or target.is_deleted or target.id != metric_id:
                raise CustomException(msg="指标不存在", status_code=404)
        else:
            target = PlatformMetricModel(**payload)
            self.db.add(target)
        for key, value in payload.items():
            setattr(target, key, value)
        await self.db.flush()
        return _field_row(target) | {"id": target.id, "status_num": target.status, "sort": target.sort}

    async def delete_metric(self, metric_id: int) -> None:
        target = await self.db.get(PlatformMetricModel, metric_id)
        if target is None or target.is_deleted:
            raise CustomException(msg="指标不存在", status_code=404)
        target.is_deleted = True
        await self.db.flush()

    async def reset_defaults(self) -> dict[str, Any]:
        """把默认指标 upsert 回表（不删除自定义指标）。"""
        created = updated = 0
        for item in DEFAULT_METRICS:
            code = item["code"]
            row = (
                await self.db.execute(
                    select(PlatformMetricModel).where(
                        PlatformMetricModel.code == code,
                        PlatformMetricModel.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalars().first()
            payload = {
                "name": item["name"],
                "group": item["group"],
                "data_type": item["data_type"],
                "unit": item.get("unit"),
                "sensitive": bool(item.get("sensitive")),
                "expression": item["expression"],
                "note": item.get("note"),
                "sort": item["sort"],
                "status": 0,
            }
            if row is None:
                self.db.add(PlatformMetricModel(code=code, **payload))
                created += 1
            else:
                for key, value in payload.items():
                    setattr(row, key, value)
                updated += 1
        await self.db.flush()
        return {"created": created, "updated": updated, "total": len(DEFAULT_METRICS)}

    @staticmethod
    def _validate_expression(expression: str, code: str) -> None:
        variables = dict.fromkeys(BASE_VARIABLES, 1.0)
        variables.update({item["code"]: 1.0 for item in DEFAULT_METRICS})
        variables[code] = 1.0
        try:
            evaluate(expression, variables)
        except ExpressionError as exc:
            raise CustomException(
                msg=f"表达式不合法：{exc}", code=CODE_PARAM_INVALID, status_code=400
            ) from exc

    # ── 取数 ─────────────────────────────────────────────────
    async def periods(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(RetailOrderModel.period_value)
                .where(RetailOrderModel.is_deleted == False)  # noqa: E712
                .distinct()
                .order_by(RetailOrderModel.period_value.desc())
                .limit(36)
            )
        ).scalars().all()
        return [str(item) for item in rows if item]

    async def platform_options(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(RetailShopModel.shop_site)
                .where(RetailShopModel.is_deleted == False)  # noqa: E712
                .distinct()
            )
        ).scalars().all()
        return sorted({normalize_platform(item) for item in rows})

    async def _shop_map(self) -> dict[int, dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    RetailShopModel.shop_id,
                    RetailShopModel.shop_name,
                    RetailShopModel.shop_site,
                ).where(RetailShopModel.is_deleted == False)  # noqa: E712
            )
        ).all()
        return {int(row[0]): {"shop_name": row[1], "shop_site": row[2]} for row in rows}

    async def _base_rows(self, period_value: str | None) -> list[dict[str, Any]]:
        data = await RetailQueryService(self.db).analysis_summary(period_value)
        shop_map = await self._shop_map()
        rows: list[dict[str, Any]] = []
        for item in data.get("items") or []:
            shop_id = int(item["shop_id"])
            shop = shop_map.get(shop_id, {})
            rows.append(
                {
                    "period": item["period_value"],
                    "shop_id": shop_id,
                    "shop_name": item.get("shop_name") or shop.get("shop_name") or f"店铺{shop_id}",
                    "platform": normalize_platform(shop.get("shop_site")),
                    "orders": int(item["order_count"]),
                    "shipped_orders": int(item["shipped_order_count"]),
                    "cancelled_orders": int(item["cancelled_order_count"]),
                    "intake": float(item["intake_untaxed"]),
                    "shipment": float(item["shipment_untaxed"]),
                    "cancelled_amount": float(item["cancelled_untaxed"]),
                    "refund": float(item["refund_untaxed"]),
                }
            )
        return rows

    def _to_row(
        self,
        base: dict[str, Any],
        configs: list[PlatformMetricModel],
        level: str,
        row_id: str,
        display: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {key: base.get(key, 0) for key in BASE_VARIABLES}
        variables.update(_rate_vars())
        variables.update(
            {
                "period": display.get("period") if display else base.get("period"),
                "platform": display.get("platform") if display else base.get("platform"),
                "shop_name": display.get("shop_name") if display else base.get("shop_name"),
                "shop_id": display.get("shop_id") if display else base.get("shop_id"),
            }
        )
        row: dict[str, Any] = {"id": row_id, "is_aggregate": {"detail": 0, "platform": 1, "total": 2}.get(level, 0),
                               "aggregate_level": level, "period_value": variables["period"]}
        # 表达式可能引用其他指标：多轮求值，最多 5 轮处理乱序依赖
        pending = list(configs)
        for _ in range(5):
            remaining: list[PlatformMetricModel] = []
            progressed = False
            for metric in pending:
                if metric.data_type == "string":
                    dim_key = DIM_KEYS.get(metric.expression.strip())
                    row[metric.code] = variables.get(dim_key) if dim_key else None
                    progressed = True
                    variables[metric.code] = row[metric.code]
                    continue
                try:
                    value = evaluate(metric.expression, variables)
                except ExpressionError:
                    remaining.append(metric)
                    continue
                # 金额/数量保留 2 位，比率保留 4 位（与页面展示、下游串联口径一致）
                row[metric.code] = round(value, 4 if metric.data_type == "percent" else 2)
                variables[metric.code] = row[metric.code]
                progressed = True
            pending = remaining
            if not pending or not progressed:
                break
        for metric in pending:
            row[metric.code] = 0 if metric.data_type != "string" else ""
        return row

    @staticmethod
    def _sum_base(rows: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["period"], row["platform"] if level == "platform" else "全部")
            bucket = buckets.get(key)
            if bucket is None:
                bucket = dict.fromkeys(BASE_SUM_KEYS, 0)
                bucket["period"] = row["period"]
                bucket["platform"] = "全部" if level == "total" else row["platform"]
                buckets[key] = bucket
            for field in BASE_SUM_KEYS:
                bucket[field] = round(float(bucket[field]) + float(row.get(field) or 0), 2)
        return [
            {
                **bucket,
                "shop_id": "",
                "shop_name": "合计" if level == "total" else f"{bucket['platform']} 小计",
            }
            for bucket in buckets.values()
        ]

    async def page(
        self, search: PlatformAnalysisQueryParam, page_no: int, page_size: int
    ) -> dict[str, Any]:
        configs = await self.configs()
        rows = await self._base_rows(search.period_value)
        if search.platform:
            rows = [row for row in rows if row["platform"] == search.platform.strip()]
        if search.shop_id is not None:
            rows = [row for row in rows if row["shop_id"] == search.shop_id]
        if search.keyword and search.keyword.strip():
            token = search.keyword.strip()
            rows = [
                row
                for row in rows
                if token in str(row["platform"]) or token in str(row["shop_name"]) or token == str(row["shop_id"])
            ]

        platform_rows = self._sum_base(rows, "platform") if rows else []
        total_rows = self._sum_base(rows, "total") if rows else []

        def _mk(base: dict[str, Any], level: str, rid: str) -> dict[str, Any]:
            display = {
                "period": base["period"],
                "platform": base["platform"],
                "shop_name": base["shop_name"],
                "shop_id": base["shop_id"],
            }
            return self._to_row(base, configs, level, rid, display)

        detail_rows = [_mk(row, "detail", f"detail-{row['period']}-{row['shop_id']}") for row in rows]
        plat_rows = [_mk(row, "platform", f"platform-{row['period']}-{row['platform']}") for row in platform_rows]
        tot_rows = [_mk(row, "total", f"total-{row['period']}") for row in total_rows]
        if search.aggregate_level == "detail":
            combined = detail_rows
        elif search.aggregate_level == "platform":
            combined = plat_rows
        else:
            combined = tot_rows + plat_rows + detail_rows

        summary = self._summary(rows, configs)
        total = len(combined)
        start = (page_no - 1) * page_size
        return {
            "items": combined[start : start + page_size],
            "columns": [_field_row(metric) for metric in configs],
            "total": total,
            "page_no": page_no,
            "page_size": page_size,
            "has_next": start + page_size < total,
            "period_value": search.period_value,
            "tax_rate": retail_tax_rate(),
            "summary": summary,
        }

    def _summary(self, rows: list[dict[str, Any]], configs: list[PlatformMetricModel]) -> dict[str, Any]:
        sums = {field: round(sum(float(row.get(field) or 0) for row in rows), 2) for field in BASE_SUM_KEYS}
        if not rows:
            sums = dict.fromkeys(BASE_SUM_KEYS, 0)
        total_row = self._to_row(
            {**sums, "period": rows[0]["period"] if rows else None, "platform": "全部", "shop_name": "合计", "shop_id": ""},
            configs,
            "total",
            "summary-total",
            {"period": rows[0]["period"] if rows else None, "platform": "全部", "shop_name": "合计", "shop_id": ""},
        )

        def pick(code: str) -> float:
            value = total_row.get(code)
            return float(value) if isinstance(value, (int, float)) else 0.0

        plat_metric_rows = [
            self._to_row(
                base,
                configs,
                "platform",
                f"summary-platform-{base['period']}-{base['platform']}",
                {
                    "period": base["period"],
                    "platform": base["platform"],
                    "shop_name": base["shop_name"],
                    "shop_id": base["shop_id"],
                },
            )
            for base in (self._sum_base(rows, "platform") if rows else [])
        ]

        return {
            "period_value": rows[0]["period"] if rows else None,
            "shop_count": len(rows),
            "platform_count": len({row["platform"] for row in rows}),
            "order_count": int(sums["orders"]),
            "shipped_order_count": int(sums["shipped_orders"]),
            "cancelled_order_count": int(sums["cancelled_orders"]),
            "intake_untaxed_sum": pick("PLT-08"),
            "shipment_untaxed_sum": pick("PLT-09"),
            "return_untaxed_sum": pick("PLT-11"),
            "net_shipment_sum": pick("PLT-12"),
            "settlement_income_sum": pick("PLT-13"),
            "hq_allocation_sum": pick("PLT-23"),
            "avg_order_value": pick("PLT-38"),
            "return_rate": pick("PLT-37"),
            "top_platforms": sorted(
                [
                    {
                        "platform": row.get("PLT-01"),
                        "order_count": int(row.get("PLT-04") or 0),
                        "intake_untaxed": float(row.get("PLT-08") or 0),
                        "shipment_untaxed": float(row.get("PLT-09") or 0),
                        "net_shipment": float(row.get("PLT-12") or 0),
                        "settlement_income": float(row.get("PLT-13") or 0),
                        "hq_allocation": float(row.get("PLT-23") or 0),
                        "return_rate": float(row.get("PLT-37") or 0),
                    }
                    for row in plat_metric_rows
                ],
                key=lambda item: item["net_shipment"],
                reverse=True,
            )[:10],
        }

    async def stats(self, period_value: str | None) -> dict[str, Any]:
        rows = await self._base_rows(period_value)
        return self._summary(rows, await self.configs())
