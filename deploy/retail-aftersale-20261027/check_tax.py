import asyncio, sys
sys.path.insert(0, ".")
from app.core.database import async_db_session
from app.modules.retail.query_service import RetailQueryService
from app.modules.retail.schema import RetailOrderQueryParam, RetailAfterSaleQueryParam

async def main():
    async with async_db_session() as db:
        svc = RetailQueryService(db)
        page = await svc.page_orders(RetailOrderQueryParam(period_value="2026-10"), 1, 1)
        print("ORDER SUMMARY", page["summary"])
        row = page["items"][0]
        print("SAMPLE", row["buyer_paid_amount"], "->", row["untaxed_amount"])
        ap = await svc.page_aftersales(RetailAfterSaleQueryParam(period_value="2026-10"), 1, 1)
        print("AFTERSALE SUMMARY", ap["summary"])
asyncio.run(main())
