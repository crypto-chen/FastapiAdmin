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
from app.modules.openapi.model import OpenApiLogModel, OpenClientModel
from app.modules.openapi.security import hash_app_secret
from app.modules.retail.aftersale_service import RetailAfterSaleSyncService
from app.modules.retail.model import (
    RetailAfterSaleItemModel,
    RetailAfterSaleModel,
    RetailOrderItemModel,
    RetailOrderModel,
    RetailShopModel,
    RetailSyncBatchModel,
)
from app.modules.retail.query_service import RetailQueryService
from app.modules.retail.schema import (
    RetailAfterSaleQueryParam,
    RetailBatchQueryParam,
    RetailOrderQueryParam,
)
from app.modules.retail.service import DEFAULT_RETAIL_PUSH_JOB_NAME, RetailSyncService
from app.modules.retail.shop_service import RetailShopService

SAMPLE_PATH = Path(__file__).parent / "data" / "qimen_retail_sample.json"
AFTER_SALE_SAMPLE_PATH = Path(__file__).parent / "data" / "qimen_aftersale_sample.json"

_TABLES = (
    "sys_user",
    "open_api_log",
    "retail_sync_batch",
    "retail_order",
    "retail_order_item",
    "retail_shop",
    "open_client",
    "retail_after_sale",
    "retail_after_sale_item",
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
            # 接单未税 = 买家实付合计 ÷ 1.13（默认税率 13%）
            assert page["summary"]["tax_rate"] == 13.0
            assert page["summary"]["untaxed_amount_sum"] == round(
                page["summary"]["buyer_paid_amount_sum"] / 1.13, 2
            )
            assert page["items"][0]["untaxed_amount"] == round(
                (page["items"][0]["buyer_paid_amount"] or 0) / 1.13, 2
            )
            detail = await service.order_detail(int(page["items"][0]["id"]))
            assert detail["order"]["period_value"] == "2026-10"
            assert detail["items"]
            batches = await service.page_batches(RetailBatchQueryParam(), 1, 20)
            assert batches["total"] == 1
            batch_detail = await service.batch_detail(int(batches["items"][0]["id"]))
            assert batch_detail["received_count"] == 6

    asyncio.run(_query())


def test_pull_orders_writes_retail_tables(retail_client: TestClient) -> None:
    """聚水潭主动拉取的订单复用同一套 upsert 和页面查询。"""
    ctx = asyncio.run(_prepare())

    async def _pull() -> None:
        async with async_db_session() as db, db.begin():
            result = await RetailSyncService(db, app_id="jushuitan_pull").pull_orders(
                ctx["sample"]["orders"],
                source="jushuitan",
                request_id="pull-test-1",
            )
            assert result.created == 6
        async with async_db_session() as db:
            count = (await db.execute(select(func.count(RetailOrderModel.id)))).scalar() or 0
            assert int(count) == 6

    asyncio.run(_pull())


def test_shop_sync_upserts(retail_client: TestClient) -> None:
    async def _sync() -> None:
        async with async_db_session() as db, db.begin():
            service = RetailShopService(db)
            first = await service.sync_shops(
                [{"shop_id": 1001, "shop_name": "测试店", "shop_site": "淘宝天猫", "session_status": 2}]
            )
            assert first["created"] == 1
            second = await service.sync_shops(
                [{"shop_id": 1001, "shop_name": "测试店-新", "shop_site": "淘宝天猫", "session_status": 2}]
            )
            assert second["updated"] == 1
        async with async_db_session() as db:
            row = (
                await db.execute(select(RetailShopModel).where(RetailShopModel.shop_id == 1001))
            ).scalars().first()
            assert row is not None
            assert row.shop_name == "测试店-新"
            assert row.shop_site == "淘宝天猫"

    asyncio.run(_sync())


def test_admin_retail_routes_registered(retail_client: TestClient) -> None:
    for path in (
        "/retail/orders/page",
        "/retail/batches/page",
        "/retail/periods",
        "/retail/aftersales/page",
    ):
        assert retail_client.get(path).status_code in (401, 403)
    assert retail_client.post("/retail/shops/sync").status_code in (401, 403)
    assert retail_client.post("/retail/aftersales/pull").status_code in (401, 403)


def test_after_sale_push_upsert_and_replay(retail_client: TestClient) -> None:
    """免鉴权推送售后单：新增 → 幂等重放 → 内容不变 → 旧版本跳过。"""
    async def _clean() -> None:
        async with async_db_session() as db, db.begin():
            await db.execute(delete(RetailAfterSaleItemModel))
            await db.execute(delete(RetailAfterSaleModel))

    asyncio.run(_clean())
    payload = json.loads(AFTER_SALE_SAMPLE_PATH.read_text(encoding="utf-8"))
    first = retail_client.post("/open/v1/retail/aftersales/sync", json=payload)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["received"] == 2
    assert data["created"] == 2
    assert data["failed"] == 0
    assert data["item_count"] == 2
    assert data["periods"] == ["2026-10"]

    # 同一份 body 命中 payload hash 幂等键 → 直接重放首次结果
    replay = retail_client.post("/open/v1/retail/aftersales/sync", json=payload)
    assert replay.status_code == 200
    assert replay.json()["data"]["duplicate"] is True

    # 换一个 request_id 再推一次 → 内容未变化，计 unchanged
    unchanged = retail_client.post(
        "/open/v1/retail/aftersales/sync",
        json=payload,
        headers={"X-Request-ID": "as-test-2"},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["data"]["unchanged"] == 2

    # 同一个 request_id 重复推 → 重放
    repeat = retail_client.post(
        "/open/v1/retail/aftersales/sync",
        json=payload,
        headers={"X-Request-ID": "as-test-2"},
    )
    assert repeat.json()["data"]["duplicate"] is True

    async def _check() -> None:
        async with async_db_session() as db:
            rows = (await db.execute(select(RetailAfterSaleModel))).scalars().all()
            assert len(rows) == 2
            row = next(item for item in rows if item.as_id == "900000001")
            assert row.shop_name == "示例旗舰店"
            assert row.status == "Confirmed"
            assert row.period_value == "2026-10"
            assert float(row.actual_refund) == 194.0
            items = (
                await db.execute(
                    select(RetailAfterSaleItemModel).where(
                        RetailAfterSaleItemModel.after_sale_id == row.id
                    )
                )
            ).scalars().all()
            assert len(items) == 1
            assert items[0].sku_id == "SKU-DEMO-001"

    asyncio.run(_check())


def test_after_sale_stale_modified_skipped(retail_client: TestClient) -> None:
    """同一售后单推送更旧的 modified 时标记 stale，不覆盖已落库数据。"""
    payload = json.loads(AFTER_SALE_SAMPLE_PATH.read_text(encoding="utf-8"))
    row = payload["data"]["datas"][0]
    stale_row = dict(row)
    stale_row["modified"] = "2026-10-21 00:00:00"
    stale_row["remark"] = "旧版本备注"

    async def _push() -> None:
        async with async_db_session() as db, db.begin():
            result = await RetailAfterSaleSyncService(db, app_id="stale_test").pull_refunds(
                [stale_row],
                source="qimen",
                request_id="stale-1",
            )
            assert result.stale == 1
            assert result.updated == 0
        async with async_db_session() as db:
            stored = (
                await db.execute(
                    select(RetailAfterSaleModel).where(RetailAfterSaleModel.as_id == "900000001")
                )
            ).scalars().first()
            assert stored is not None
            assert stored.remark == "尺码不合适"

    asyncio.run(_push())


def test_after_sale_query_page_and_summary(retail_client: TestClient) -> None:
    """售后页查询与汇总；单独运行时先补一份样例数据（与推送用例解耦）。"""
    payload = json.loads(AFTER_SALE_SAMPLE_PATH.read_text(encoding="utf-8"))
    retail_client.post("/open/v1/retail/aftersales/sync", json=payload)

    async def _query() -> None:
        async with async_db_session() as db:
            service = RetailQueryService(db)
            page = await service.page_aftersales(
                RetailAfterSaleQueryParam(period_value="2026-10"), 1, 20
            )
            assert page["total"] == 2
            assert page["summary"]["actual_refund_sum"] == 282.0
            assert page["summary"]["untaxed_actual_refund_sum"] == 249.56
            detail = await service.aftersale_detail(page["items"][0]["id"])
            assert detail["after_sale"]["as_id"] in {"900000001", "900000002"}
            assert detail["after_sale"]["untaxed_actual_refund"] is not None
            assert len(detail["items"]) == 1

    asyncio.run(_query())


def test_analysis_summary_counts_only_shipped_orders(retail_client: TestClient) -> None:
    """货物出货 = 已发货订单（默认 status=Sent）；取消单不计，售后退款冲减净额。"""

    async def _clean() -> None:
        async with async_db_session() as db, db.begin():
            await db.execute(delete(RetailOrderItemModel))
            await db.execute(delete(RetailOrderModel))
            await db.execute(delete(RetailAfterSaleItemModel))
            await db.execute(delete(RetailAfterSaleModel))

    asyncio.run(_clean())

    rows = [
        {"so_id": "AS-S1", "shop_id": 1, "status": "Sent", "order_date": "2026-10-02 10:00:00",
         "buyer_paid_amount": 113.0},
        {"so_id": "AS-S2", "shop_id": 1, "status": "Sent", "order_date": "2026-10-03 10:00:00",
         "buyer_paid_amount": 226.0},
        {"so_id": "AS-S3", "shop_id": 1, "status": "WaitConfirm", "order_date": "2026-10-04 10:00:00",
         "buyer_paid_amount": 339.0},
        {"so_id": "AS-S4", "shop_id": 2, "status": "Cancelled", "order_date": "2026-10-05 10:00:00",
         "buyer_paid_amount": 500.0},
    ]
    refunds = [
        {"as_id": "AS-A1", "so_id": "AS-S1", "shop_id": 1, "as_date": "2026-10-10 00:00:00",
         "refund": 56.5, "freight": 0, "payment": 0, "free_amount": 0, "status": "Confirmed"},
        # 订单还是 WaitConfirm（未发货）→ 不算「发货后申请退款」，不计入退货
        {"as_id": "AS-A2", "so_id": "AS-S3", "shop_id": 1, "as_date": "2026-10-11 00:00:00",
         "refund": 113.0, "freight": 0, "payment": 0, "free_amount": 0, "status": "Confirmed"},
    ]

    async def _run() -> None:
        async with async_db_session() as db, db.begin():
            await RetailSyncService(db, app_id="analysis_test").pull_orders(
                rows, source="qimen", request_id="analysis-orders-1"
            )
        async with async_db_session() as db, db.begin():
            await RetailAfterSaleSyncService(db, app_id="analysis_test").pull_refunds(
                refunds, source="qimen", request_id="analysis-refund-1"
            )
        async with async_db_session() as db:
            data = await RetailQueryService(db).analysis_summary("2026-10")
            total = data["total"]
            assert data["shipped_statuses"] == ["Sent"]
            assert data["tax_rate"] == 13.0
            # 取消单计入接单与退货，但不入出货
            assert total["order_count"] == 4
            assert total["shipped_order_count"] == 2
            assert total["cancelled_order_count"] == 1
            # 接单未税 = 1178 ÷ 1.13；出货未税 = 339 ÷ 1.13（只算已发货）
            assert total["intake_untaxed"] == 1042.48
            assert total["shipment_untaxed"] == 300.0
            # 退货退款 = 取消单 500 ÷ 1.13 + 发货后售后 56.5 ÷ 1.13（未发货订单上的售后不算）
            assert total["cancelled_untaxed"] == -442.48
            assert total["refund_untaxed"] == -50.0
            assert total["return_untaxed"] == -492.48
            assert total["net_shipment_untaxed"] == -192.48
            # 营销结算收入 PLT-13 = 对外出货净额 × 10%
            assert data["settlement_rate"] == 10.0
            assert total["settlement_income_untaxed"] == -19.25
            # 总部分摊 PLT-23 = 结算收入 × 4%
            assert total["hq_allocation_untaxed"] == -0.77
            # 净额为负时以出货额作退货率分母：492.48 ÷ 300
            assert total["return_rate"] == 1.6416

    asyncio.run(_run())


def test_platform_analysis_requires_client_flag(retail_client: TestClient) -> None:
    """平台渠道分析接口：应用未开开关返回 403/40102，开启后可读。"""
    app_id = "pytest_platform_analysis"
    secret = "platform-secret-123"

    async def _reset(allow: bool) -> None:
        async with async_db_session() as db, db.begin():
            await db.execute(delete(OpenClientModel).where(OpenClientModel.app_id == app_id))
            db.add(
                OpenClientModel(
                    app_id=app_id,
                    name="平台渠道分析测试",
                    secret_hash=await hash_app_secret(secret),
                    status=0,
                    token_ttl_seconds=600,
                    rate_limit=600,
                    allow_platform_analysis=allow,
                )
            )

    async def _enable() -> None:
        async with async_db_session() as db, db.begin():
            row = (
                await db.execute(select(OpenClientModel).where(OpenClientModel.app_id == app_id))
            ).scalars().first()
            assert row is not None
            row.allow_platform_analysis = True

    asyncio.run(_reset(False))
    token_res = retail_client.post(
        "/open/v1/auth/token", json={"app_id": app_id, "app_secret": secret}
    )
    assert token_res.status_code == 200, token_res.text
    token = token_res.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    denied = retail_client.get("/open/v1/retail/platform/analysis", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == 40102

    asyncio.run(_enable())
    allowed = retail_client.get("/open/v1/retail/platform/analysis", headers=headers)
    assert allowed.status_code == 200, allowed.text
    data = allowed.json()["data"]
    assert data["app_id"] == app_id
    assert {"tax_rate", "settlement_rate", "items", "total"} <= set(data)
    assert {"intake_untaxed", "shipment_untaxed", "return_untaxed",
            "net_shipment_untaxed", "settlement_income_untaxed"} <= set(data["total"])
    # 未带令牌直接 401
    assert retail_client.get("/open/v1/retail/platform/analysis").status_code == 401
