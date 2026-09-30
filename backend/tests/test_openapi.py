"""开放接口（/open/v1）端到端测试：换令牌、权限、限流、取数口径、调用日志。

本文件自带 app fixture（只建开放接口相关表）：仓库既有的
``InitializeData.init_db`` 全量建表路径在 SQLite 下会因索引重名
（``master_person.org_id`` 与 ``master_person_org.id`` 同名索引）中断，
与本模块无关，故此处独立初始化，保证用例可独立运行。
"""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis.asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import create_app
from app.core.base_model import MappedBase
from app.core.base_schema import AuthSchema, CoreUserSchema, JWTPayloadSchema
from app.core.database import async_db_session, async_engine
from app.core.security import create_access_token
from app.modules.metric.model import MetricDefModel, MetricValueModel
from app.modules.openapi.model import OpenApiLogModel, OpenClientModel
from app.modules.openapi.schema import OpenClientCreateSchema, OpenClientUpdateSchema
from app.modules.openapi.service import OpenClientService

APP_ID = "pytest_bi"
METRIC_CODE = "pytest_openapi_metric"
METRIC_EXCEL_CODE = "EXP-99-z"
BATCH_ID = "pytest-openapi"

_TABLES = (
    "sys_user",
    "master_org",
    "master_dept",
    "metric_def",
    "metric_run",
    "metric_value",
    "open_client",
    "open_api_log",
)


@asynccontextmanager
async def _openapi_lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:
    tables = [MappedBase.metadata.tables[name] for name in _TABLES]
    async with async_engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all, tables=tables)
    app.state.redis = redis.asyncio.Redis.from_url("redis://localhost:6379/0")
    yield


@pytest.fixture(scope="module")
def openapi_client() -> Generator[TestClient, Any, None]:
    app = create_app()
    app.router.lifespan_context = _openapi_lifespan
    with TestClient(app) as client:
        yield client


async def _prepare() -> None:
    """构造测试用指标与结果（最新版本 2，含一条组织合计与一条部门明细）。"""
    async with async_db_session() as db, db.begin():
        await db.execute(delete(MetricValueModel).where(MetricValueModel.batch_id == BATCH_ID))
        await db.execute(delete(MetricDefModel).where(MetricDefModel.code == METRIC_CODE))
        await db.execute(delete(OpenClientModel).where(OpenClientModel.app_id == APP_ID))
        await db.execute(delete(OpenClientModel).where(OpenClientModel.app_id == f"{APP_ID}_limit"))
        await db.execute(delete(OpenClientModel).where(OpenClientModel.app_id == f"{APP_ID}_log"))
        metric = MetricDefModel(
            code=METRIC_CODE, name="测试指标", excel_code=METRIC_EXCEL_CODE, period_type="month", status=0
        )
        db.add(metric)
        await db.flush()
        now = datetime.now(UTC)
        db.add_all(
            [
                MetricValueModel(
                    metric_id=metric.id,
                    period_type="month",
                    period_value="2026-08",
                    value=100.5,
                    calc_version=1,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
                MetricValueModel(
                    metric_id=metric.id,
                    period_type="month",
                    period_value="2026-08",
                    value=120.75,
                    calc_version=2,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
                MetricValueModel(
                    metric_id=metric.id,
                    period_type="month",
                    period_value="2026-07",
                    value=80,
                    calc_version=1,
                    calc_time=now,
                    batch_id=BATCH_ID,
                ),
                MetricValueModel(
                    metric_id=metric.id,
                    period_type="month",
                    period_value="2026-08",
                    value=60,
                    calc_version=2,
                    calc_time=now,
                    batch_id=BATCH_ID,
                    dept_code="D01",
                    dept_name="销售部",
                ),
            ]
        )


def _auth() -> AuthSchema:
    """管理端服务层用的认证上下文（超管，权限校验直接放行）。"""
    return AuthSchema(user=CoreUserSchema(id=1, username="tester", name="tester", is_superuser=True))


async def _admin_create_client(app_id: str, **extra) -> dict:
    async with async_db_session() as db, db.begin():
        out = await OpenClientService(_auth(), db).create(
            OpenClientCreateSchema(app_id=app_id, name="测试应用", **extra)
        )
        return {"id": out.id, "app_secret": out.app_secret}


async def _admin_update_client(client_id: int, **payload) -> None:
    async with async_db_session() as db, db.begin():
        await OpenClientService(_auth(), db).update(client_id, OpenClientUpdateSchema(**payload), _redis())


async def _admin_reset_secret(client_id: int) -> str:
    async with async_db_session() as db, db.begin():
        out = await OpenClientService(_auth(), db).reset_secret(client_id, _redis())
        return out.app_secret


def _redis():
    return redis.asyncio.Redis.from_url("redis://localhost:6379/0")


def _token(test_client, app_id: str, app_secret: str) -> str:
    resp = test_client.post(
        "/open/v1/auth/token", json={"app_id": app_id, "app_secret": app_secret}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def admin_headers() -> dict[str, str]:
    """构造一个签名合法但没有 Redis 会话的管理端令牌：用于验证两类令牌互不通用。"""
    token = create_access_token(
        JWTPayloadSchema(sub="no-such-session", exp=datetime.now(UTC) + timedelta(hours=1))
    )
    return {"Authorization": f"Bearer {token}"}


def test_open_token_and_query(openapi_client):
    asyncio.run(_prepare())
    client = asyncio.run(_admin_create_client(APP_ID))
    secret = client["app_secret"]
    assert secret and "secret_hash" not in client

    bad = openapi_client.post("/open/v1/auth/token", json={"app_id": APP_ID, "app_secret": "wrong"})
    assert bad.status_code == 401

    token = _token(openapi_client, APP_ID, secret)
    headers = {"Authorization": f"Bearer {token}"}

    metrics = openapi_client.get("/open/v1/metrics", headers=headers)
    assert metrics.status_code == 200, metrics.text
    codes = [item["code"] for item in metrics.json()["data"]["items"]]
    assert METRIC_CODE in codes
    excel_codes = [item["excel_code"] for item in metrics.json()["data"]["items"]]
    assert METRIC_EXCEL_CODE in excel_codes

    query = openapi_client.post(
        "/open/v1/metrics/query",
        headers=headers,
        json={
            "metrics": [METRIC_CODE, "not_exists"],
            "period_type": "month",
            "period_start": "2026-07",
            "period_end": "2026-08",
        },
    )
    assert query.status_code == 200, query.text
    data = query.json()["data"]
    # 每个期间只返回最新计算版本：2026-08 取 calc_version=2 的 120.75，不是 100.5
    assert [(i["period_value"], i["value"]) for i in data["items"]] == [
        ("2026-07", 80.0),
        ("2026-08", 120.75),
    ]
    assert all(i["dept_code"] is None for i in data["items"])
    assert all(i["excel_code"] == METRIC_EXCEL_CODE for i in data["items"])
    assert data["errors"] == [{"metric_code": "not_exists", "reason": "指标不存在"}]
    assert data["summary"]["item_count"] == 2

    # 支持直接传 Excel 科目编码取数
    by_excel = openapi_client.post(
        "/open/v1/metrics/query",
        headers=headers,
        json={"metrics": [METRIC_EXCEL_CODE], "period_start": "2026-08", "period_end": "2026-08", "total_only": True},
    )
    assert by_excel.status_code == 200, by_excel.text
    excel_totals = by_excel.json()["data"]["totals"]
    assert excel_totals[0]["metric_code"] == METRIC_CODE
    assert excel_totals[0]["excel_code"] == METRIC_EXCEL_CODE
    assert excel_totals[0]["value"] == 120.75

    wide = openapi_client.post(
        "/open/v1/metrics/query",
        headers=headers,
        json={"metrics": [METRIC_CODE], "period_start": "2026-08", "period_end": "2026-08", "format": "wide"},
    )
    assert wide.status_code == 200, wide.text
    rows = wide.json()["data"]["rows"]
    assert len(rows) == 1 and rows[0][METRIC_CODE] == 120.75

    # 只要合计：items 为空，合计值在 totals 中
    total_only = openapi_client.post(
        "/open/v1/metrics/query",
        headers=headers,
        json={
            "metrics": [METRIC_CODE],
            "period_start": "2026-07",
            "period_end": "2026-08",
            "total_only": True,
        },
    )
    assert total_only.status_code == 200, total_only.text
    totals = total_only.json()["data"]["totals"]
    assert total_only.json()["data"]["items"] == []
    assert [(row["period_value"], row["value"]) for row in totals] == [
        ("2026-07", 80.0),
        ("2026-08", 120.75),
    ]
    assert totals[0]["metric_code"] == METRIC_CODE

    dept = openapi_client.post(
        "/open/v1/metrics/query",
        headers=headers,
        json={"metrics": [METRIC_CODE], "level": "dept"},
    )
    assert dept.status_code == 403, dept.text

    bad_period = openapi_client.post(
        "/open/v1/metrics/query",
        headers=headers,
        json={"metrics": [METRIC_CODE], "period_start": "2026/08", "period_end": "2026-09"},
    )
    assert bad_period.status_code == 400, bad_period.text

    no_token = openapi_client.post("/open/v1/metrics/query", json={"metrics": [METRIC_CODE]})
    assert no_token.status_code == 401

    # 管理端令牌不能用于开放接口
    crossed = openapi_client.get("/open/v1/metrics", headers=admin_headers())
    assert crossed.status_code == 401, crossed.text


def test_open_rate_limit_and_status(openapi_client):
    asyncio.run(_prepare())
    client = asyncio.run(_admin_create_client(f"{APP_ID}_limit", rate_limit=1))
    token = _token(openapi_client, f"{APP_ID}_limit", client["app_secret"])
    headers = {"Authorization": f"Bearer {token}"}

    first = openapi_client.get("/open/v1/orgs", headers=headers)
    assert first.status_code == 200, first.text
    second = openapi_client.get("/open/v1/orgs", headers=headers)
    assert second.status_code == 429, second.text
    assert second.json()["code"] == 40103

    # 停用后旧令牌立即失效
    asyncio.run(_admin_update_client(client["id"], status=1))
    disabled = openapi_client.get("/open/v1/metrics", headers=headers)
    # 令牌已被撤销（401）或应用状态校验拦截（403），两者都表示旧令牌不可再用
    assert disabled.status_code in (401, 403), disabled.text
    assert disabled.json()["code"] in (40100, 40101)

    # 重置密钥后旧密钥不可再换令牌
    new_secret = asyncio.run(_admin_reset_secret(client["id"]))
    assert new_secret != client["app_secret"]
    old = openapi_client.post(
        "/open/v1/auth/token", json={"app_id": f"{APP_ID}_limit", "app_secret": client["app_secret"]}
    )
    assert old.status_code == 401


def test_open_call_log_written(openapi_client):
    asyncio.run(_prepare())
    client = asyncio.run(_admin_create_client(f"{APP_ID}_log"))
    token = _token(openapi_client, f"{APP_ID}_log", client["app_secret"])
    call = openapi_client.get("/open/v1/metrics", headers={"Authorization": f"Bearer {token}"})
    assert call.status_code == 200, call.text

    async def _logs() -> list[OpenApiLogModel]:
        async with async_db_session() as db:
            return list(
                (
                    await db.execute(
                        select(OpenApiLogModel)
                        .where(OpenApiLogModel.app_id == f"{APP_ID}_log")
                        .order_by(OpenApiLogModel.id.desc())
                    )
                )
                .scalars()
                .all()
            )

    rows = asyncio.run(_logs())
    assert rows, "开放接口调用未落日志"
    assert rows[0].path == "/open/v1/metrics"
    assert rows[0].http_status == 200

def test_admin_routes_registered(openapi_client):
    """管理端路由存在（未带令牌时应为 401/403，而不是 404）。"""
    for path in (
        "/openapi/client/page",
        "/openapi/client/detail/1",
        "/openapi/client/reset-secret/1",
        "/openapi/log/page",
    ):
        assert openapi_client.get(path).status_code != 404
    assert openapi_client.post("/openapi/client/create", json={}).status_code != 404
    assert openapi_client.request("DELETE", "/openapi/client/delete", json=[]).status_code != 404
