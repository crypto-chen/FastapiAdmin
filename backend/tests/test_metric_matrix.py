"""指标表单（多指标并排）与批量重算的服务层测试。

独立建表（只建本用例用到的表），避免走 ``InitializeData.init_db`` 在 SQLite 下的
索引重名问题；与 ``test_openapi.py`` 使用同一套初始化策略。
"""

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete

from app.core.base_model import MappedBase
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session, async_engine
from app.core.exceptions import CustomException
from app.modules.metric.model import MetricDefModel, MetricValueModel
from app.modules.metric.schema import (
    MetricBatchRunRequestSchema,
    MetricDefQueryParam,
    MetricMatrixQueryParam,
)
from app.modules.metric.service import MetricService
from app.modules.system.user.model import UserModel  # noqa: F401  分页结果左连 sys_user，本文件建表需注册该表

BATCH_ID = "pytest-matrix"
CODE_A = "pytest_matrix_a"
CODE_B = "pytest_matrix_b"
CODE_LONG_DESC = "pytest_matrix_long_desc"
PERIOD = "2026-08"

_TABLES = ("master_org", "master_dept", "metric_def", "metric_run", "metric_value", "sys_user")


@pytest.fixture(scope="module", autouse=True)
def metric_tables() -> Generator[None, Any, None]:
    """建表（模块级一次），供本文件所有用例复用。"""

    async def _setup() -> None:
        tables = [MappedBase.metadata.tables[name] for name in _TABLES]
        async with async_engine.begin() as conn:
            await conn.run_sync(MappedBase.metadata.create_all, tables=tables)

    asyncio.run(_setup())
    yield


def _auth() -> AuthSchema:
    return AuthSchema(user=CoreUserSchema(id=1, username="tester", name="tester", is_superuser=True))


async def _prepare() -> tuple[int, int]:
    """两个启用指标：A 有新旧两个版本 + 一条部门明细，B 只有一个版本和另一期间。"""
    async with async_db_session() as db, db.begin():
        await db.execute(delete(MetricValueModel).where(MetricValueModel.batch_id == BATCH_ID))
        await db.execute(delete(MetricDefModel).where(MetricDefModel.code.in_([CODE_A, CODE_B])))
        metric_a = MetricDefModel(
            code=CODE_A, name="矩阵指标A", period_type="month", status=0, description="口径说明A"
        )
        metric_b = MetricDefModel(code=CODE_B, name="矩阵指标B", period_type="month", status=0)
        db.add_all([metric_a, metric_b])
        await db.flush()
        now = datetime.now(UTC)
        db.add_all(
            [
                # A：同期间两个版本 → 只应取最新版本 2
                MetricValueModel(
                    metric_id=metric_a.id,
                    period_type="month",
                    period_value=PERIOD,
                    value=100,
                    calc_version=1,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
                MetricValueModel(
                    metric_id=metric_a.id,
                    period_type="month",
                    period_value=PERIOD,
                    value=120.5,
                    calc_version=2,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
                MetricValueModel(
                    metric_id=metric_a.id,
                    period_type="month",
                    period_value=PERIOD,
                    value=60,
                    calc_version=2,
                    calc_time=now,
                    batch_id=BATCH_ID,
                    dept_code="D01",
                    dept_name="销售部",
                ),
                # B：本期一条组织合计；另一期间不参与本期查询
                MetricValueModel(
                    metric_id=metric_b.id,
                    period_type="month",
                    period_value=PERIOD,
                    value=7.25,
                    calc_version=1,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
                MetricValueModel(
                    metric_id=metric_b.id,
                    period_type="month",
                    period_value="2026-07",
                    value=99,
                    calc_version=1,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
            ]
        )
        return int(metric_a.id), int(metric_b.id)


def _matrix(metric_ids: str, level: str = "org"):
    async def _run():
        async with async_db_session() as db:
            return await MetricService(_auth(), db).matrix(
                MetricMatrixQueryParam(metric_ids=metric_ids, period_value=PERIOD, level=level)
            )

    return asyncio.run(_run())


def test_matrix_returns_multiple_metrics_with_latest_version(metric_tables) -> None:
    metric_a, metric_b = asyncio.run(_prepare())

    result = _matrix(f"{metric_a},{metric_b}")

    assert [item.name for item in result.columns] == ["矩阵指标A", "矩阵指标B"]
    # 口径随列返回，供前端在指标名上悬浮展示
    assert result.columns[0].description == "口径说明A"
    assert result.columns[1].description is None
    # 组织合计层级：两个指标的组织行合并成一行
    assert result.total == 1
    row = result.items[0]
    assert row.dept_code is None
    assert row.values[str(metric_a)] == 120.5  # 最新版本 2，不是旧版本 100
    assert row.values[str(metric_b)] == 7.25
    assert row.calc_versions[str(metric_a)] == 2
    assert row.calc_versions[str(metric_b)] == 1


def test_matrix_level_all_includes_department_rows(metric_tables) -> None:
    metric_a, metric_b = asyncio.run(_prepare())

    result = _matrix(f"{metric_a},{metric_b}", level="all")

    assert result.total == 2
    # 组织合计行在前，部门明细行在后
    assert result.items[0].dept_code is None
    assert result.items[1].dept_code == "D01"
    assert result.items[1].values[str(metric_a)] == 60


def test_matrix_accepts_whitespace_separated_ids(metric_tables) -> None:
    metric_a, metric_b = asyncio.run(_prepare())

    result = _matrix(f" {metric_a} , {metric_b} ")

    assert len(result.columns) == 2


def test_matrix_rejects_empty_or_unknown_metric(metric_tables) -> None:
    asyncio.run(_prepare())

    with pytest.raises(CustomException):
        _matrix(" ")
    with pytest.raises(CustomException):
        _matrix("999999")


def test_run_batch_calculates_selected_metrics(metric_tables) -> None:
    """批量重算按勾选的指标执行；未配置取数规则的指标计入跳过、不算失败。"""
    metric_a, metric_b = asyncio.run(_prepare())

    async def _run():
        async with async_db_session() as db:
            return await MetricService(_auth(), db).run_batch(
                MetricBatchRunRequestSchema(metric_ids=[metric_a, metric_b], period_value=PERIOD)
            )

    summary = asyncio.run(_run())

    assert summary.metric_count == 2
    assert summary.success == 2
    assert summary.failed == []
    assert {item["metric_code"] for item in summary.results} == {CODE_A, CODE_B}


def test_run_batch_without_ids_covers_all_enabled_metrics(metric_tables) -> None:
    asyncio.run(_prepare())

    async def _run():
        async with async_db_session() as db:
            return await MetricService(_auth(), db).run_batch(MetricBatchRunRequestSchema())

    summary = asyncio.run(_run())

    assert summary.metric_count >= 2
    assert summary.failed == []


def test_page_tolerates_description_over_create_limit(metric_tables) -> None:
    """脚本直写的长口径说明（超过创建上限）不能让「指标定义」分页整体 500。

    seed_crm_person_metrics.py 直写 ORM，实测备注 508 字，曾导致
    ``MetricDefOutSchema`` 输出校验失败、前端报「组件渲染异常」。
    """
    long_description = "口径说明" * 200  # 800 字，超过创建上限

    async def _seed_then_page():
        async with async_db_session() as db, db.begin():
            await db.execute(delete(MetricDefModel).where(MetricDefModel.code == CODE_LONG_DESC))
            db.add(
                MetricDefModel(
                    code=CODE_LONG_DESC,
                    name="长备注指标",
                    period_type="month",
                    status=0,
                    description=long_description,
                )
            )
        async with async_db_session() as db:
            return await MetricService(_auth(), db).page(
                MetricDefQueryParam(code=CODE_LONG_DESC), page_no=1, page_size=10
            )

    result = asyncio.run(_seed_then_page())

    assert result.total == 1
    assert result.items[0].description == long_description
