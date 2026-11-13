"""指标口径版本：历史规则 / 当前规则 / 期间钉版。"""

import asyncio
from collections.abc import Generator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.core.base_model import MappedBase
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session, async_engine
from app.modules.metric.engine import _load_metric_context, execute_metric_calc
from app.modules.metric.model import (
    MetricDefModel,
    MetricDefVersionModel,
    MetricPeriodVersionModel,
    MetricValueModel,
)
from app.modules.metric.schema import MetricDefUpdateSchema, MetricMatrixQueryParam
from app.modules.metric.service import MetricService
from app.modules.metric.versions import (
    CURRENT,
    HISTORICAL,
    load_def_snapshot,
    resolve_def_version,
)
from app.modules.system.user.model import UserModel  # noqa: F401

_TABLES = (
    "master_org",
    "master_dept",
    "metric_def",
    "metric_def_version",
    "metric_period_version",
    "metric_run",
    "metric_value",
    "sys_user",
)

CODE = "pytest_rule_version"
PERIOD = "2026-10"


@pytest.fixture(scope="module", autouse=True)
def metric_tables() -> Generator[None, Any, None]:
    async def _setup() -> None:
        tables = [MappedBase.metadata.tables[name] for name in _TABLES]
        async with async_engine.begin() as conn:
            await conn.run_sync(MappedBase.metadata.create_all, tables=tables)

    asyncio.run(_setup())
    yield


def _auth() -> AuthSchema:
    return AuthSchema(user=CoreUserSchema(id=1, username="tester", name="tester", is_superuser=True))


async def _cleanup(db) -> None:
    metric_ids = (
        await db.execute(select(MetricDefModel.id).where(MetricDefModel.code.like(f"{CODE}%")))
    ).scalars().all()
    if metric_ids:
        await db.execute(
            delete(MetricPeriodVersionModel).where(MetricPeriodVersionModel.metric_id.in_(metric_ids))
        )
        await db.execute(delete(MetricValueModel).where(MetricValueModel.metric_id.in_(metric_ids)))
        await db.execute(
            delete(MetricDefVersionModel).where(MetricDefVersionModel.metric_id.in_(metric_ids))
        )
        await db.execute(delete(MetricDefModel).where(MetricDefModel.id.in_(metric_ids)))
    await db.flush()


@pytest.fixture(autouse=True)
def _clean_between_tests(metric_tables) -> Generator[None, Any, None]:
    async def _do() -> None:
        async with async_db_session() as db, db.begin():
            await _cleanup(db)

    asyncio.run(_do())
    yield
    asyncio.run(_do())


async def _create_metric(db, *, version: int = 1, measures: dict | None = None) -> MetricDefModel:
    metric = MetricDefModel(
        code=CODE,
        name="口径版本测试",
        category="测试",
        period_type="month",
        status=0,
        version=version,
        measures=measures or {"kind": "account_balance_filter", "account_prefix": "1001"},
    )
    db.add(metric)
    await db.flush()
    return metric


def test_historical_and_current_rule_resolution() -> None:
    async def _run() -> None:
        async with async_db_session() as db, db.begin():
            await _cleanup(db)
            metric = await _create_metric(db, version=2)
            db.add_all(
                [
                    MetricDefVersionModel(
                        metric_id=metric.id,
                        version=1,
                        effective_from=date(1970, 1, 1),
                        effective_to=date(2026, 10, 31),
                        code=CODE,
                        name="旧口径",
                        category="测试",
                        period_type="month",
                        measures={"kind": "account_balance_filter", "account_prefix": "1001"},
                    ),
                    MetricDefVersionModel(
                        metric_id=metric.id,
                        version=2,
                        effective_from=date(2026, 11, 1),
                        code=CODE,
                        name="新口径",
                        category="测试",
                        period_type="month",
                        measures={"kind": "account_balance_filter", "account_prefix": "2001"},
                    ),
                ]
            )
            await db.flush()

            assert await resolve_def_version(db, metric.id, "month", PERIOD, HISTORICAL) == 1
            assert await resolve_def_version(db, metric.id, "month", PERIOD, CURRENT) == 2
            assert await resolve_def_version(db, metric.id, "month", "2026-11", HISTORICAL) == 2

            old = await load_def_snapshot(db, metric.id, 1, metric)
            new = await load_def_snapshot(db, metric.id, 2, metric)
            assert old["measures"]["account_prefix"] == "1001"
            assert new["measures"]["account_prefix"] == "2001"

    asyncio.run(_run())


def test_matrix_uses_active_def_version_not_global_calc_version() -> None:
    async def _run() -> None:
        async with async_db_session() as db, db.begin():
            await _cleanup(db)
            metric = await _create_metric(db, version=2)
            db.add(
                MetricPeriodVersionModel(
                    metric_id=metric.id,
                    period_type="month",
                    period_value=PERIOD,
                    pinned_def_version=1,
                    active_def_version=2,
                    last_calc_version=2,
                    last_rule_mode=CURRENT,
                )
            )
            db.add_all(
                [
                    MetricValueModel(
                        metric_id=metric.id,
                        period_type="month",
                        period_value=PERIOD,
                        value=50,
                        version=1,
                        calc_version=5,
                    ),
                    MetricValueModel(
                        metric_id=metric.id,
                        period_type="month",
                        period_value=PERIOD,
                        value=20,
                        version=2,
                        calc_version=1,
                    ),
                ]
            )
            await db.flush()

            service = MetricService(_auth(), db)
            result = await service.matrix(
                MetricMatrixQueryParam(metric_ids=str(metric.id), period_value=PERIOD, level="org")
            )
            assert result.items[0].values[str(metric.id)] == 20
            assert result.items[0].calc_versions[str(metric.id)] == 1

            row = (
                await db.execute(
                    select(MetricPeriodVersionModel).where(
                        MetricPeriodVersionModel.metric_id == metric.id,
                        MetricPeriodVersionModel.period_value == PERIOD,
                    )
                )
            ).scalars().one()
            row.active_def_version = 1
            await db.flush()
            result = await service.matrix(
                MetricMatrixQueryParam(metric_ids=str(metric.id), period_value=PERIOD, level="org")
            )
            assert result.items[0].values[str(metric.id)] == 50

    asyncio.run(_run())


def test_update_publishes_new_definition_version() -> None:
    async def _run() -> None:
        async with async_db_session() as db, db.begin():
            await _cleanup(db)
            service = MetricService(_auth(), db)
            created = await service.create(
                MetricDefUpdateSchema(
                    code=CODE,
                    name="口径版本测试",
                    category="测试",
                    period_type="month",
                    measures={"kind": "account_balance_filter", "account_prefix": "1001"},
                )
            )
            assert created.version == 1

            updated = await service.update(
                created.id,
                MetricDefUpdateSchema(
                    code=CODE,
                    name="口径版本测试",
                    category="测试",
                    period_type="month",
                    measures={"kind": "account_balance_filter", "account_prefix": "2001"},
                    effective_from=date(2026, 1, 1),
                ),
            )
            assert updated.version == 2

            rows = (
                await db.execute(
                    select(MetricDefVersionModel)
                    .where(MetricDefVersionModel.metric_id == created.id)
                    .order_by(MetricDefVersionModel.version)
                )
            ).scalars().all()
            assert [row.version for row in rows] == [1, 2]
            assert rows[0].effective_to == date(2025, 12, 31)
            assert rows[0].measures["account_prefix"] == "1001"
            assert rows[1].effective_from == date(2026, 1, 1)
            assert rows[1].measures["account_prefix"] == "2001"

    asyncio.run(_run())


def test_engine_context_uses_selected_rule_snapshot() -> None:
    async def _run() -> None:
        async with async_db_session() as db, db.begin():
            await _cleanup(db)
            component_a = MetricDefModel(
                code=f"{CODE}_a",
                name="组成A",
                category="测试",
                period_type="month",
                status=0,
                measures={"kind": "account_balance_filter", "account_prefix": "1001"},
            )
            component_c = MetricDefModel(
                code=f"{CODE}_c",
                name="组成C",
                category="测试",
                period_type="month",
                status=0,
                measures={"kind": "account_balance_filter", "account_prefix": "2001"},
            )
            derived = MetricDefModel(
                code=f"{CODE}_b",
                name="汇总指标",
                category="测试",
                period_type="month",
                status=0,
                version=1,
                measures={"kind": "metric_sum", "component_metric_codes": [f"{CODE}_a"]},
            )
            db.add_all([component_a, component_c, derived])
            await db.flush()
            db.add_all(
                [
                    MetricDefVersionModel(
                        metric_id=derived.id,
                        version=1,
                        effective_from=date(1970, 1, 1),
                        effective_to=date(2026, 10, 31),
                        code=derived.code,
                        name=derived.name,
                        category="测试",
                        period_type="month",
                        measures={"kind": "metric_sum", "component_metric_codes": [f"{CODE}_a"]},
                    ),
                    MetricDefVersionModel(
                        metric_id=derived.id,
                        version=2,
                        effective_from=date(2026, 11, 1),
                        code=derived.code,
                        name=derived.name,
                        category="测试",
                        period_type="month",
                        measures={"kind": "metric_sum", "component_metric_codes": [f"{CODE}_c"]},
                    ),
                ]
            )
            derived.version = 2
            await db.flush()

            derived_id = int(derived.id)

        historical = await _load_metric_context(derived_id, PERIOD, None, HISTORICAL)
        current = await _load_metric_context(derived_id, PERIOD, None, CURRENT)
        assert [code for _id, code in historical["component_metrics"]] == [f"{CODE}_a"]
        assert [code for _id, code in current["component_metrics"]] == [f"{CODE}_c"]
        assert historical["metric_version"] == 1
        assert current["metric_version"] == 2

    asyncio.run(_run())


def test_recalculation_switches_active_rule_and_keeps_pinned_version() -> None:
    async def _run() -> None:
        async with async_db_session() as db, db.begin():
            await _cleanup(db)
            component_a = MetricDefModel(
                code=f"{CODE}_a",
                name="组成A",
                category="测试",
                period_type="month",
                status=0,
                measures={"kind": "account_balance_filter", "account_prefix": "1001"},
            )
            component_c = MetricDefModel(
                code=f"{CODE}_c",
                name="组成C",
                category="测试",
                period_type="month",
                status=0,
                measures={"kind": "account_balance_filter", "account_prefix": "2001"},
            )
            derived = MetricDefModel(
                code=f"{CODE}_b",
                name="汇总指标",
                category="测试",
                period_type="month",
                status=0,
                version=1,
                measures={"kind": "metric_sum", "component_metric_codes": [f"{CODE}_a"]},
            )
            db.add_all([component_a, component_c, derived])
            await db.flush()
            now = datetime.now(UTC)
            db.add_all(
                [
                    MetricValueModel(
                        metric_id=component_a.id,
                        period_type="month",
                        period_value=PERIOD,
                        value=100,
                        version=1,
                        calc_version=1,
                        calc_time=now,
                    ),
                    MetricValueModel(
                        metric_id=component_c.id,
                        period_type="month",
                        period_value=PERIOD,
                        value=200,
                        version=1,
                        calc_version=1,
                        calc_time=now,
                    ),
                    MetricDefVersionModel(
                        metric_id=derived.id,
                        version=1,
                        effective_from=date(1970, 1, 1),
                        effective_to=date(2026, 10, 31),
                        code=derived.code,
                        name=derived.name,
                        category="测试",
                        period_type="month",
                        measures={"kind": "metric_sum", "component_metric_codes": [f"{CODE}_a"]},
                    ),
                    MetricDefVersionModel(
                        metric_id=derived.id,
                        version=2,
                        effective_from=date(2026, 11, 1),
                        code=derived.code,
                        name=derived.name,
                        category="测试",
                        period_type="month",
                        measures={"kind": "metric_sum", "component_metric_codes": [f"{CODE}_c"]},
                    ),
                ]
            )
            derived.version = 2
            derived_id = int(derived.id)

        historical = await execute_metric_calc(derived_id, PERIOD, rule_mode=HISTORICAL)
        assert historical["total"] == 100
        assert historical["def_version"] == 1

        current = await execute_metric_calc(derived_id, PERIOD, rule_mode=CURRENT)
        assert current["total"] == 200
        assert current["def_version"] == 2

        async with async_db_session() as db:
            row = (
                await db.execute(
                    select(MetricPeriodVersionModel).where(
                        MetricPeriodVersionModel.metric_id == derived_id,
                        MetricPeriodVersionModel.period_value == PERIOD,
                    )
                )
            ).scalars().one()
            assert row.pinned_def_version == 1
            assert row.active_def_version == 2
            assert row.last_rule_mode == CURRENT

        back = await execute_metric_calc(derived_id, PERIOD, rule_mode=HISTORICAL)
        assert back["total"] == 100
        async with async_db_session() as db:
            row = (
                await db.execute(
                    select(MetricPeriodVersionModel).where(
                        MetricPeriodVersionModel.metric_id == derived_id,
                        MetricPeriodVersionModel.period_value == PERIOD,
                    )
                )
            ).scalars().one()
            assert row.pinned_def_version == 1
            assert row.active_def_version == 1

    asyncio.run(_run())
