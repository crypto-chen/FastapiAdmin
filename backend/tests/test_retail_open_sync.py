"""零售数据推送开放接口测试：免鉴权、幂等、upsert、旧版本跳过、指标批次回放。"""

import asyncio
import json
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import redis.asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import create_app
from app.config.setting import settings
from app.core.base_model import MappedBase
from app.core.database import async_db_session, async_engine
from app.modules.metadata.model import (
    MetaSyncJobModel,
    MetaSyncRunModel,
    SourceObjectModel,
    SourceSystemModel,
)
from app.modules.openapi.model import OpenApiLogModel
from app.modules.retail.model import RetailOrderItemModel, RetailOrderModel, RetailSyncBatchModel
from app.modules.retail.query_service import RetailQueryService
from app.modules.retail.schema import RetailBatchQueryParam, RetailOrderQueryParam
from app.modules.retail.service import DEFAULT_RETAIL_PUSH_JOB_NAME

SAMPLE_PATH = Path(__file__).parent / "data" / "qimen_retail_sample.json"

_TABLES = (
    "sys_user",
    "open_api_log",
    "retail_sync_batch",
    "retail_order",
    "retail_order_item",
    "meta_source_system",
    "meta_source_object",
    "meta_sync_job",
    "meta_sync_run",
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:
    tables = [MappedBase.metadata.tables[name] for name in _TABLES]
    async with async_engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all, tables=tables)
    app.state.redis = redis.asyncio.Redis.from_url("redis://localhost:6379/0")
    yield


@pytest.fixture(scope="module")
def retail_client() -> Generator[TestClient, Any, None]:
    app = create_app()
    app.router.lifespan_context = _lifespan
    with TestClient(app) as client:
        yield client


async def _prepare() -> dict[str, Any]:
    search_orders = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    settings.RETAIL_SYNC_JOB_ID = None  # 走“按默认任务名自动查找”分支
    async with async_db_session() as db, db.begin():
        await db.execute(delete(RetailOrderItemModel))
        await db.execute(delete(RetailOrderModel))
        await db.execute(delete(RetailSyncBatchModel))
        await db.execute(delete(MetaSyncRunModel))
        await db.execute(
            delete(MetaSyncJobModel).where(
                MetaSyncJobModel.name.in_(
                    [DEFAULT_RETAIL_PUSH_JOB_NAME, "pytest-retail-push-job"]
                )
            )
        )
        await db.execute(delete(OpenApiLogModel))

        system = (
            await db.execute(
                select(SourceSystemModel).where(SourceSystemModel.code == "pytest_retail_push")
            )
        ).scalars().first()
        if system is None:
            system = SourceSystemModel(
                code="pytest_retail_push",
                name="零售推送测试",
                connector_type="push",
                status=0,
            )
            db.add(system)
            await db.flush()
        obj = (
            await db.execute(
                select(SourceObjectModel).where(
                    SourceObjectModel.system_id == system.id,
                    SourceObjectModel.code == "/retail/orders/sync",
                )
            )
        ).scalars().first()
        if obj is None:
            obj = SourceObjectModel(
                system_id=system.id,
                code="/retail/orders/sync",
                name="零售订单推送",
                query_type="api",
                status=0,
            )
            db.add(obj)
            await db.flush()
        job = MetaSyncJobModel(
            name=DEFAULT_RETAIL_PUSH_JOB_NAME,
            source_system_id=system.id,
            source_object_id=obj.id,
            cron_expr="0 0 0 31 2 ?",
            request_params={},
            sync_mode="full",
            status=0,
        )
        db.add(job)
        await db.flush()
        return {"job_id": job.id, "sample": search_orders}


def _headers(request_id: str | None = None) -> dict[str, str]:
    return {"X-Request-ID": request_id} if request_id else {}


def test_sync_without_token_idempotent_and_metric_feed(retail_client: TestClient) -> None:
    ctx = asyncio.run(_prepare())
    sample = ctx["sample"]
    headers = _headers("req-1")
    assert "Authorization" not in headers

    first = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=headers,
        json=sample,
    )
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["received"] == 6
    assert data["created"] == 6
    assert data["failed"] == 0
    assert data["periods"] == ["2026-10"]
    assert data["item_count"] > 0
    assert data["metric_sync"][0]["status"] == "published"
    assert data["metric_sync"][0]["row_count"] == 6

    async def _counts() -> tuple[int, int, int]:
        async with async_db_session() as db:
            orders = (await db.execute(select(func.count(RetailOrderModel.id)))).scalar() or 0
            items = (await db.execute(select(func.count(RetailOrderItemModel.id)))).scalar() or 0
            batches = (await db.execute(select(func.count(RetailSyncBatchModel.id)))).scalar() or 0
            return int(orders), int(items), int(batches)

    assert asyncio.run(_counts())[0] == 6
    assert asyncio.run(_counts())[2] == 1

    # 同一请求ID重复提交：返回首次结果，不再新增订单/批次
    duplicate = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=headers,
        json=sample,
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["data"]["duplicate"] is True
    assert duplicate.json()["data"]["created"] == 6
    assert asyncio.run(_counts())[0] == 6
    assert asyncio.run(_counts())[2] == 1

    async def _latest_run() -> MetaSyncRunModel:
        async with async_db_session() as db:
            row = (
                await db.execute(
                    select(MetaSyncRunModel)
                    .where(MetaSyncRunModel.job_id == ctx["job_id"])
                    .order_by(MetaSyncRunModel.id.desc())
                )
            ).scalars().first()
            assert row is not None
            return row

    run = asyncio.run(_latest_run())
    assert run.row_count == 6
    assert len(run.rows_json["datas"]) == 6
    assert run.rows_json["source"] == "retail_push"

    # 新版本更新：金额与批次同步
    updated_order = dict(sample["orders"][0])
    updated_order["buyer_paid_amount"] = "70.0"
    updated_order["modified"] = "2026-10-23 12:00:00"
    updated = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=_headers("req-2"),
        json={"request_id": "req-2", "source": "qimen", "orders": [updated_order]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["updated"] == 1

    async def _amount(so_id: str) -> Any:
        async with async_db_session() as db:
            row = (
                await db.execute(
                    select(RetailOrderModel).where(RetailOrderModel.so_id == so_id)
                )
            ).scalars().first()
            assert row is not None
            return row.buyer_paid_amount

    first_so_id = str(sample["orders"][0]["so_id"])
    assert str(asyncio.run(_amount(first_so_id))) == "70.0000"

    # 旧 version 不允许覆盖新数据
    stale_order = dict(sample["orders"][0])
    stale_order["buyer_paid_amount"] = "60.0"
    stale_order["modified"] = "2026-10-22 00:00:00"
    stale = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=_headers("req-3"),
        json={"request_id": "req-3", "orders": [stale_order]},
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["data"]["stale"] == 1
    assert str(asyncio.run(_amount(first_so_id))) == "70.0000"


def test_sync_accepts_bare_order_list_and_data_wrapper(retail_client: TestClient) -> None:
    ctx = asyncio.run(_prepare())
    order = ctx["sample"]["orders"][5]
    resp = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=_headers("req-list"),
        json=[order],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["created"] == 1

    wrapped = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=_headers("req-data"),
        json={"data": {"orders": [ctx["sample"]["orders"][4]], "has_next": False}},
    )
    assert wrapped.status_code == 200, wrapped.text
    assert wrapped.json()["data"]["created"] == 1


def test_sync_accepts_orders_json_string(retail_client: TestClient) -> None:
    """兼容低代码平台把数组序列化成字符串后放进扁平 data 的情况。"""
    ctx = asyncio.run(_prepare())
    resp = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=_headers("req-json-string"),
        json={
            "request_id": "req-json-string",
            "orders": json.dumps(ctx["sample"]["orders"], ensure_ascii=False),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["created"] == 6


def test_sync_accepts_raw_json_string_body(retail_client: TestClient) -> None:
    """兼容低代码平台 payload_type=raw：整个 body 是 JSON 字符串。"""
    ctx = asyncio.run(_prepare())
    resp = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers={**_headers("req-raw-string"), "Content-Type": "application/json"},
        content=json.dumps(ctx["sample"], ensure_ascii=False),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["created"] == 6


def test_sync_accepts_python_repr_body(retail_client: TestClient) -> None:
    """兼容平台把参数直接 str(dict) 后发送（单引号、True/False）。"""
    ctx = asyncio.run(_prepare())
    resp = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers={**_headers("req-python-repr"), "Content-Type": "application/json"},
        content=repr(ctx["sample"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["created"] == 6


def test_sync_works_without_authorization_header(retail_client: TestClient) -> None:
    ctx = asyncio.run(_prepare())
    resp = retail_client.post(
        "/open/v1/retail/orders/sync",
        json=ctx["sample"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["created"] == 6


def test_sync_rejects_empty_payload(retail_client: TestClient) -> None:
    asyncio.run(_prepare())
    resp = retail_client.post(
        "/open/v1/retail/orders/sync",
        json={"request_id": "req-empty", "orders": []},
    )
    assert resp.status_code == 400, resp.text


def test_admin_retail_query_service(retail_client: TestClient) -> None:
    ctx = asyncio.run(_prepare())
    pushed = retail_client.post(
        "/open/v1/retail/orders/sync",
        headers=_headers("req-admin"),
        json=ctx["sample"],
    )
    assert pushed.status_code == 200, pushed.text

    async def _query() -> None:
        async with async_db_session() as db:
            service = RetailQueryService(db)
            page = await service.page_orders(RetailOrderQueryParam(period_value="2026-10"), 1, 20)
            assert page["total"] == 6
            assert page["summary"]["order_count"] == 6
            detail = await service.order_detail(int(page["items"][0]["id"]))
            assert detail["order"]["period_value"] == "2026-10"
            assert detail["items"]
            batches = await service.page_batches(RetailBatchQueryParam(), 1, 20)
            assert batches["total"] == 1
            batch_detail = await service.batch_detail(int(batches["items"][0]["id"]))
            assert batch_detail["received_count"] == 6

    asyncio.run(_query())


def test_admin_retail_routes_registered(retail_client: TestClient) -> None:
    for path in ("/retail/orders/page", "/retail/batches/page", "/retail/periods"):
        assert retail_client.get(path).status_code in (401, 403)
