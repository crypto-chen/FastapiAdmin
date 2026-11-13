"""指标口径版本解析。

把「期间」映射到「定义版本」：

- ``historical``：优先取该期间已钉住的 ``pinned_def_version``；未钉住时按
  ``effective_from/effective_to`` 解析当时生效的版本，最后回落指标当前版本。
- ``current``：直接取指标当前已发布版本，忽略生效期，用于口径纠错后的追溯重算。

计算结果写入 ``metric_value.version``；期间表 ``metric_period_version`` 只负责
记录「历史默认口径」和「当前生效口径」，不改写历史结果行。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .model import MetricDefModel, MetricDefVersionModel, MetricPeriodVersionModel, MetricValueModel

HISTORICAL = "historical"
CURRENT = "current"
RULE_MODES = (HISTORICAL, CURRENT)


def normalize_rule_mode(value: str | None) -> str:
    """归一化口径模式；缺省按历史规则。"""
    mode = str(value or HISTORICAL).strip().lower()
    return mode if mode in RULE_MODES else HISTORICAL


def _parse_period_start(period_type: str, period_value: str) -> date:
    value = str(period_value or "").strip()
    try:
        if period_type == "year":
            return date(int(value[:4]), 1, 1)
        if period_type == "day":
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        return datetime.strptime(value[:7], "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"期间值格式不支持: {period_value}") from exc


def period_start_date(period_type: str, period_value: str) -> date:
    """返回期间首日；口径版本按期间首日解析，避免月中切换导致同月两套算法。"""
    return _parse_period_start(period_type, period_value)


def next_period_start_date(period_type: str, period_value: str) -> date:
    """返回下一期间首日，作为「默认从下期生效」的生效日期。"""
    start = _parse_period_start(period_type, period_value)
    if period_type == "year":
        return date(start.year + 1, 1, 1)
    if period_type == "day":
        return start + timedelta(days=1)
    if start.month == 12:
        return date(start.year + 1, 1, 1)
    return date(start.year, start.month + 1, 1)


def snapshot_from_metric(metric: MetricDefModel) -> dict[str, Any]:
    """把指标定义当前行转成版本快照（纯数据，脱离 ORM 会话后仍可用）。"""
    return {
        "metric_id": int(metric.id),
        "version": int(metric.version or 1),
        "code": str(metric.code),
        "name": str(metric.name or metric.code),
        "category": str(metric.category or ""),
        "excel_code": metric.excel_code,
        "period_type": str(metric.period_type or "month"),
        "sensitivity": int(metric.sensitivity or 0),
        "formula": metric.formula,
        "dimensions": dict(metric.dimensions or {}),
        "measures": dict(metric.measures or {}),
        "source_entity_id": metric.source_entity_id,
        "status": int(metric.status or 0),
        "description": metric.description,
    }


async def load_def_snapshot(
    db: AsyncSession,
    metric_id: int,
    version: int,
    metric: MetricDefModel | None = None,
) -> dict[str, Any]:
    """读取指定定义版本的快照；版本行不存在时回落指标当前行（兼容存量数据）。"""
    row = (
        await db.execute(
            select(MetricDefVersionModel).where(
                MetricDefVersionModel.metric_id == metric_id,
                MetricDefVersionModel.version == int(version),
            )
        )
    ).scalars().first()
    if row is not None:
        return {
            "metric_id": int(row.metric_id),
            "version": int(row.version),
            "code": str(row.code),
            "name": str(row.name or row.code),
            "category": str(row.category or ""),
            "excel_code": row.excel_code,
            "period_type": str(row.period_type or "month"),
            "sensitivity": int(row.sensitivity or 0),
            "formula": row.formula,
            "dimensions": dict(row.dimensions or {}),
            "measures": dict(row.measures or {}),
            "source_entity_id": row.source_entity_id,
            "status": int(row.status or 0),
            "description": row.description,
        }
    metric = metric or await db.get(MetricDefModel, metric_id)
    if metric is None:
        raise ValueError(f"指标定义不存在: {metric_id}")
    snapshot = snapshot_from_metric(metric)
    snapshot["version"] = int(version or metric.version or 1)
    return snapshot


async def resolve_def_version(
    db: AsyncSession,
    metric_id: int,
    period_type: str,
    period_value: str,
    rule_mode: str = HISTORICAL,
) -> int:
    """解析某期间应使用的定义版本号。"""
    if normalize_rule_mode(rule_mode) == CURRENT:
        version = (
            await db.execute(select(MetricDefModel.version).where(MetricDefModel.id == metric_id))
        ).scalars().first()
        return int(version or 1)

    pinned = (
        await db.execute(
            select(MetricPeriodVersionModel.pinned_def_version).where(
                MetricPeriodVersionModel.metric_id == metric_id,
                MetricPeriodVersionModel.period_type == period_type,
                MetricPeriodVersionModel.period_value == period_value,
            )
        )
    ).scalars().first()
    if pinned is not None:
        return int(pinned)

    start = period_start_date(period_type, period_value)
    effective = (
        await db.execute(
            select(MetricDefVersionModel.version)
            .where(
                MetricDefVersionModel.metric_id == metric_id,
                MetricDefVersionModel.effective_from <= start,
                or_(
                    MetricDefVersionModel.effective_to.is_(None),
                    MetricDefVersionModel.effective_to >= start,
                ),
            )
            .order_by(MetricDefVersionModel.effective_from.desc(), MetricDefVersionModel.version.desc())
            .limit(1)
        )
    ).scalars().first()
    if effective is not None:
        return int(effective)

    version = (
        await db.execute(select(MetricDefModel.version).where(MetricDefModel.id == metric_id))
    ).scalars().first()
    return int(version or 1)


async def resolve_def_versions(
    db: AsyncSession,
    metric_ids: list[int],
    period_type: str,
    period_value: str,
    rule_mode: str = HISTORICAL,
) -> dict[int, int]:
    """批量解析多个指标的期间版本，避免逐指标查询。"""
    ids = sorted({int(item) for item in metric_ids})
    if not ids:
        return {}

    current_versions = {
        int(metric_id): int(version or 1)
        for metric_id, version in (
            await db.execute(
                select(MetricDefModel.id, MetricDefModel.version).where(MetricDefModel.id.in_(ids))
            )
        ).all()
    }
    if normalize_rule_mode(rule_mode) == CURRENT:
        return {metric_id: current_versions.get(metric_id, 1) for metric_id in ids}

    pinned = {
        int(metric_id): int(version)
        for metric_id, version in (
            await db.execute(
                select(
                    MetricPeriodVersionModel.metric_id,
                    MetricPeriodVersionModel.pinned_def_version,
                ).where(
                    MetricPeriodVersionModel.metric_id.in_(ids),
                    MetricPeriodVersionModel.period_type == period_type,
                    MetricPeriodVersionModel.period_value == period_value,
                )
            )
        ).all()
    }
    missing = [metric_id for metric_id in ids if metric_id not in pinned]
    effective: dict[int, int] = {}
    if missing:
        start = period_start_date(period_type, period_value)
        rows = (
            await db.execute(
                select(
                    MetricDefVersionModel.metric_id,
                    MetricDefVersionModel.version,
                )
                .where(
                    MetricDefVersionModel.metric_id.in_(missing),
                    MetricDefVersionModel.effective_from <= start,
                    or_(
                        MetricDefVersionModel.effective_to.is_(None),
                        MetricDefVersionModel.effective_to >= start,
                    ),
                )
                .order_by(
                    MetricDefVersionModel.metric_id.asc(),
                    MetricDefVersionModel.effective_from.desc(),
                    MetricDefVersionModel.version.desc(),
                )
            )
        ).all()
        for metric_id, version in rows:
            effective.setdefault(int(metric_id), int(version))

    return {
        metric_id: pinned.get(metric_id)
        or effective.get(metric_id)
        or current_versions.get(metric_id, 1)
        for metric_id in ids
    }


async def pin_period_version(
    db: AsyncSession,
    *,
    metric_id: int,
    period_type: str,
    period_value: str,
    pinned_version: int,
    active_version: int,
    calc_version: int,
    rule_mode: str,
) -> MetricPeriodVersionModel:
    """写入/更新期间口径指针；``pinned_def_version`` 首次写入后不再变化。"""
    row = (
        await db.execute(
            select(MetricPeriodVersionModel)
            .where(
                MetricPeriodVersionModel.metric_id == metric_id,
                MetricPeriodVersionModel.period_type == period_type,
                MetricPeriodVersionModel.period_value == period_value,
            )
            .with_for_update()
        )
    ).scalars().first()
    if row is None:
        row = MetricPeriodVersionModel(
            metric_id=metric_id,
            period_type=period_type,
            period_value=period_value,
            pinned_def_version=int(pinned_version or 1),
            active_def_version=int(active_version or pinned_version or 1),
            last_calc_version=int(calc_version or 1),
            last_rule_mode=normalize_rule_mode(rule_mode),
        )
        db.add(row)
    else:
        row.active_def_version = int(active_version or row.pinned_def_version or 1)
        row.last_calc_version = int(calc_version or row.last_calc_version or 1)
        row.last_rule_mode = normalize_rule_mode(rule_mode)
    await db.flush()
    return row


async def latest_calc_version(
    db: AsyncSession,
    metric_id: int,
    period_type: str,
    period_value: str,
    version: int,
) -> int | None:
    """指定指标、期间、定义版本下的最新计算版本。"""
    value = (
        await db.execute(
            select(func.max(MetricValueModel.calc_version)).where(
                MetricValueModel.metric_id == metric_id,
                MetricValueModel.period_type == period_type,
                MetricValueModel.period_value == period_value,
                MetricValueModel.version == int(version),
            )
        )
    ).scalars().first()
    return int(value) if value is not None else None


async def active_def_versions(
    db: AsyncSession,
    metric_ids: list[int],
    period_value: str,
    period_type: str = "month",
) -> dict[int, int]:
    """读取多个指标在某期间「当前生效」的定义版本。

    没有期间钉版记录时，按生效期解析当时的口径（而不是直接取指标当前版本），
    避免「新口径发布后、历史期间还没重算」导致查询取不到行。
    """
    ids = sorted({int(item) for item in metric_ids})
    if not ids:
        return {}
    current = {
        int(metric_id): int(version or 1)
        for metric_id, version in (
            await db.execute(
                select(MetricDefModel.id, MetricDefModel.version).where(MetricDefModel.id.in_(ids))
            )
        ).all()
    }
    rows = (
        await db.execute(
            select(MetricPeriodVersionModel.metric_id, MetricPeriodVersionModel.active_def_version).where(
                MetricPeriodVersionModel.metric_id.in_(ids),
                MetricPeriodVersionModel.period_value == period_value,
            )
        )
    ).all()
    active = {int(metric_id): int(version) for metric_id, version in rows}
    missing = [metric_id for metric_id in ids if metric_id not in active]
    historical = (
        await resolve_def_versions(db, missing, period_type, period_value, HISTORICAL)
        if missing
        else {}
    )
    return {
        metric_id: active.get(metric_id)
        or historical.get(metric_id)
        or current.get(metric_id, 1)
        for metric_id in ids
    }
