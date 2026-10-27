"""平台分析（指标中心 → 平台分析）：接口鉴权 + 取数与平台归一。"""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import redis.asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import create_app
from app.core.base_model import MappedBase
from app.core.database import async_db_session, async_engine
from app.modules.platform.schema import PlatformAnalysisQueryParam
from app.modules.platform.service import PlatformAnalysisService, normalize_platform
from app.modules.retail.model import (
    RetailAfterSaleItemModel,
    RetailAfterSaleModel,
    RetailOrderItemModel,
    RetailOrderModel,
    RetailShopModel,
)

_TABLES = (
    "sys_user",
    "open_api_log",
    "retail_order",
    "retail_order_item",
    "retail_after_sale",
    "retail_after_sale_item",
    "retail_shop",
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:
    tables = [MappedBase.metadata.tables[name] for name in _TABLES]
    async with async_engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all, tables=tables)
    app.state.redis = redis.asyncio.Redis.from_url("redis://localhost:6379/0")
    yield


@pytest.fixture(scope="module")
def platform_client() -> Generator[TestClient, Any, None]:
    app = create_app()
    app.router.lifespan_context = _lifespan
    with TestClient(app) as client:
        yield client


def test_normalize_platform() -> None:
    assert normalize_platform("淘宝天猫") == "天猫"
    assert normalize_platform("京东POP") == "京东"
    assert normalize_platform("拼多多") == "拼多多"
    assert normalize_platform("抖音小店") == "抖音"
    assert normalize_platform("商家自有商城") == "其他"
    assert normalize_platform(None) == "其他"


def test_platform_page_requires_auth(platform_client: TestClient) -> None:
    for path in ("/platform/page", "/platform/fields", "/platform/periods"):
        assert platform_client.get(path).status_code in (401, 403)


def test_platform_service_aggregates(platform_client: TestClient) -> None:
    async def _seed() -> None:
        async with async_db_session() as db, db.begin():
            await db.execute(delete(RetailOrderItemModel))
            await db.execute(delete(RetailOrderModel))
            await db.execute(delete(RetailAfterSaleItemModel))
            await db.execute(delete(RetailAfterSaleModel))
            await db.execute(delete(RetailShopModel))
            db.add_all(
                [
                    RetailShopModel(source="jushuitan", shop_id=1, shop_name="天猫店", shop_site="淘宝天猫"),
                    RetailShopModel(source="jushuitan", shop_id=2, shop_name="京东店", shop_site="京东"),
                ]
            )
            rows = [
                {"so_id": "P-1", "shop_id": 1, "status": "Sent", "order_date": "2026-10-02 10:00:00",
                 "buyer_paid_amount": 113.0},
                {"so_id": "P-2", "shop_id": 1, "status": "Cancelled", "order_date": "2026-10-03 10:00:00",
                 "buyer_paid_amount": 500.0},
                {"so_id": "P-3", "shop_id": 2, "status": "Sent", "order_date": "2026-10-04 10:00:00",
                 "buyer_paid_amount": 226.0},
            ]
            for row in rows:
                db.add(
                    RetailOrderModel(
                        order_key=f"qimen:{row['shop_id']}:{row['so_id']}",
                        source="qimen",
                        shop_id=row["shop_id"],
                        so_id=row["so_id"],
                        status=row["status"],
                        order_date=__import__("datetime").datetime.fromisoformat(row["order_date"]),
                        period_value="2026-10",
                        buyer_paid_amount=row["buyer_paid_amount"],
                        content_hash=f"h-{row['so_id']}",
                        first_batch_id="test",
                        last_batch_id="test",
                    )
                )

    asyncio.run(_seed())

    async def _check() -> None:
        async with async_db_session() as db:
            service = PlatformAnalysisService(db)
            # 平台小计
            page = await service.page(
                PlatformAnalysisQueryParam(period_value="2026-10", aggregate_level="platform"), 1, 20
            )
            assert page["total"] == 2
            by_platform = {row["PLT-01"]: row for row in page["items"]}
            assert set(by_platform) == {"天猫", "京东"}
            assert by_platform["京东"]["PLT-08"] == 200.0
            assert by_platform["京东"]["PLT-09"] == 200.0
            assert by_platform["京东"]["PLT-12"] == 200.0
            assert by_platform["京东"]["PLT-13"] == 20.0
            assert by_platform["京东"]["PLT-23"] == 0.8  # 20 × 4%
            # 客单价 = 接单未税 ÷ 有效订单数（剔除取消）
            assert by_platform["京东"]["PLT-38"] == 200.0  # 200 / 1
            assert by_platform["天猫"]["PLT-08"] == 542.48
            assert by_platform["天猫"]["PLT-09"] == 100.0
            assert by_platform["天猫"]["PLT-11"] == -442.48
            assert by_platform["天猫"]["PLT-12"] == -342.48
            assert by_platform["天猫"]["PLT-23"] == -1.37  # -34.25 × 4%
            assert by_platform["天猫"]["PLT-38"] == 542.48  # 542.48 / (2-1)

            # 店铺明细
            detail = await service.page(
                PlatformAnalysisQueryParam(period_value="2026-10", aggregate_level="detail"), 1, 20
            )
            assert detail["total"] == 2
            assert {row["PLT-02"] for row in detail["items"]} == {"天猫店", "京东店"}

            # 汇总
            summary = page["summary"]
            assert summary["platform_count"] == 2
            assert summary["shop_count"] == 2
            assert summary["order_count"] == 3
            assert summary["intake_untaxed_sum"] == 742.48
            assert summary["net_shipment_sum"] == -142.48
            assert summary["hq_allocation_sum"] == -0.57  # 0.8 + (-1.37)
            assert summary["avg_order_value"] == 371.24  # 742.48 / (3-1)
            assert summary["top_platforms"][0]["platform"] == "京东"

            assert {item["field_code"] for item in await service.fields()} >= {
                "PLT-08", "PLT-09", "PLT-11", "PLT-12", "PLT-13", "PLT-37",
                "PLT-23",
                "PLT-38",
            }

    asyncio.run(_check())
