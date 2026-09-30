"""聚水潭连接配置与销售出库取数服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.utils.common_util import search_to_dict
from app.utils.crypto_util import CryptoUtil

from .aggregate import AMOUNT_SOURCES, summarize
from .client import (
    DATE_TYPE_IO_DATE,
    STATUS_CONFIRMED,
    TIME_FORMAT,
    JushuitanClient,
    JushuitanClientConfig,
    JushuitanError,
    month_range,
)
from .crud import JushuitanConnectionCRUD
from .model import JushuitanConnectionModel
from .schema import (
    JushuitanConnectionCreateSchema,
    JushuitanConnectionOutSchema,
    JushuitanConnectionQueryParam,
    JushuitanConnectionUpdateSchema,
    JushuitanMonthlyQuerySchema,
    JushuitanMonthlySummarySchema,
    JushuitanSalesOutboundQuerySchema,
    JushuitanSalesOutboundResultSchema,
)


class JushuitanService:
    """聚水潭连接配置与查询服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _crud(self) -> JushuitanConnectionCRUD:
        return JushuitanConnectionCRUD(self.auth, self.db)

    # ------------------------------------------------------------------ #
    # 连接配置
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_out(obj: JushuitanConnectionModel) -> JushuitanConnectionOutSchema:
        out = JushuitanConnectionOutSchema.model_validate(obj)
        out.has_secret = bool(obj.app_secret)
        out.has_token = bool(obj.access_token)
        return out

    @staticmethod
    def _client_from(obj: JushuitanConnectionModel) -> JushuitanClient:
        return JushuitanClient(
            JushuitanClientConfig(
                base_url=obj.base_url,
                app_key=obj.app_key,
                app_secret=CryptoUtil.decrypt(obj.app_secret) if obj.app_secret else "",
                access_token=CryptoUtil.decrypt(obj.access_token) if obj.access_token else "",
                timeout=obj.timeout,
            )
        )

    async def _connection(self, source_id: int) -> JushuitanConnectionModel:
        obj = await self._crud().get_or_404(id=source_id, msg="该聚水潭连接不存在")
        if obj.status == 1:
            raise CustomException(msg="该聚水潭连接已停用")
        return obj

    async def detail(self, id: int) -> JushuitanConnectionOutSchema:
        obj = await self._crud().get_or_404(id=id, msg="该聚水潭连接不存在")
        return self._to_out(obj)

    async def get_list(self, search: JushuitanConnectionQueryParam | None = None) -> list[JushuitanConnectionOutSchema]:
        objs = await self._crud().get_list(search=search_to_dict(search), order_by=[{"id": "asc"}])
        return [self._to_out(obj) for obj in objs]

    async def page(
        self,
        search: JushuitanConnectionQueryParam | None,
        page_no: int,
        page_size: int,
        order_by: list[dict] | None = None,
    ) -> PageResultSchema[JushuitanConnectionOutSchema]:
        result = await self._crud().page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=order_by or [{"id": "asc"}],
            search=search_to_dict(search),
        )
        return PageResultSchema[JushuitanConnectionOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=[self._to_out(obj) for obj in result.items],
        )

    async def create(self, data: JushuitanConnectionCreateSchema) -> JushuitanConnectionOutSchema:
        if await self._crud().get(name=data.name):
            raise CustomException(msg="创建失败，连接名称已存在")
        payload = data.model_dump(exclude_none=True)
        for field in ("app_secret", "access_token"):
            if payload.get(field):
                payload[field] = CryptoUtil.encrypt(payload[field])
        obj = await self._crud().create(data=payload)
        return self._to_out(obj)

    async def update(self, id: int, data: JushuitanConnectionUpdateSchema) -> JushuitanConnectionOutSchema:
        await self._crud().get_or_404(id=id, msg="更新失败，该聚水潭连接不存在")
        exist = await self._crud().get(name=data.name)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，连接名称已存在")

        payload = data.model_dump(exclude_unset=True)
        for field in ("app_secret", "access_token"):
            if payload.get(field):
                payload[field] = CryptoUtil.encrypt(payload[field])
            else:
                payload.pop(field, None)
        await self._crud().update(id=id, data=payload)
        obj = await self._crud().get_or_404(id=id)
        return self._to_out(obj)

    async def delete(self, ids: list[int]) -> None:
        if not ids:
            raise CustomException(msg="删除失败，删除对象不能为空")
        await self._crud().delete(ids=ids)

    async def test_connection(self, id: int) -> dict:
        obj = await self._connection(id)
        try:
            async with self._client_from(obj) as client:
                return await client.test_connection()
        except JushuitanError as e:
            raise CustomException(msg=f"连接失败：{e}") from e
        except Exception as e:
            raise CustomException(msg=f"连接失败：{e}") from e

    # ------------------------------------------------------------------ #
    # 销售出库取数
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_range(data: JushuitanSalesOutboundQuerySchema) -> tuple[datetime, datetime]:
        if data.period_value:
            return month_range(data.period_value)
        if data.begin and data.end:
            try:
                begin = datetime.strptime(data.begin.strip(), TIME_FORMAT)
                end = datetime.strptime(data.end.strip(), TIME_FORMAT)
            except ValueError as e:
                raise CustomException(msg="时间格式应为 yyyy-MM-dd HH:mm:ss") from e
            if end < begin:
                raise CustomException(msg="结束时间不能早于起始时间")
            return begin, end
        raise CustomException(msg="请传入 period_value(YYYY-MM) 或 begin/end")

    @staticmethod
    def _biz_extra(obj: JushuitanConnectionModel, data: JushuitanSalesOutboundQuerySchema) -> dict[str, Any]:
        """把连接默认值与请求参数合成接口 biz 过滤条件。"""
        extra: dict[str, Any] = {"date_type": int(data.date_type)}
        shop_id = data.shop_id if data.shop_id is not None else obj.shop_id
        offline = data.is_offline_shop if data.is_offline_shop is not None else bool(obj.is_offline_shop)
        if shop_id is not None:
            extra["shop_id"] = int(shop_id)
        if offline:
            extra["is_offline_shop"] = True
        status = (data.status or "").strip()
        if status:
            extra["status"] = status
        if data.wms_co_id:
            extra["wms_co_id"] = int(data.wms_co_id)
        return extra

    async def _fetch_rows(self, obj: JushuitanConnectionModel, data: JushuitanSalesOutboundQuerySchema) -> tuple[datetime, datetime, list[dict]]:
        begin, end = self._resolve_range(data)
        extra = self._biz_extra(obj, data)
        rows: list[dict] = []
        try:
            async with self._client_from(obj) as client:
                async for row in client.iter_sales_outbound(begin, end, page_size=data.page_size, **extra):
                    rows.append(row)
                    if len(rows) >= data.max_rows:
                        break
        except JushuitanError as e:
            raise CustomException(msg=f"查询失败：{e}") from e
        return begin, end, rows

    async def query_sales_outbound(self, data: JushuitanSalesOutboundQuerySchema) -> JushuitanSalesOutboundResultSchema:
        """按时间段（或月度期间）拉取销售出库单，默认只要已出库、按出库时间过滤。"""
        obj = await self._connection(data.source_id)
        begin, end, rows = await self._fetch_rows(obj, data)
        summary = summarize(rows, amount_source="items.auto")
        return JushuitanSalesOutboundResultSchema(
            source_id=data.source_id,
            begin=begin.strftime(TIME_FORMAT),
            end=end.strftime(TIME_FORMAT),
            order_count=summary["order_count"],
            item_qty=summary["item_qty"],
            tax_inclusive_amount=summary["tax_inclusive_amount"],
            untaxed_amount=summary["untaxed_amount"],
            amount_source="items.auto",
            rows=rows if data.include_rows else [],
        )

    async def monthly_summary(self, data: JushuitanMonthlyQuerySchema) -> JushuitanMonthlySummarySchema:
        """零售出库未税总金额（月度指标）。"""
        if data.amount_source not in AMOUNT_SOURCES:
            raise CustomException(msg=f"不支持的取数口径: {data.amount_source}（可选：{', '.join(AMOUNT_SOURCES)}）")
        obj = await self._connection(data.source_id)
        begin, end, rows = await self._fetch_rows(obj, data)
        summary = summarize(
            rows,
            amount_source=data.amount_source,
            tax_rate=data.tax_rate,
            tax_inclusive=data.tax_inclusive,
            by_shop=data.by_shop,
            auto_fields=data.auto_fields,
        )
        period = data.period_value or begin.strftime("%Y-%m")
        return JushuitanMonthlySummarySchema(
            period_value=period,
            order_count=summary["order_count"],
            item_qty=summary["item_qty"],
            tax_inclusive_amount=summary["tax_inclusive_amount"],
            untaxed_amount=summary["untaxed_amount"],
            tax_rate=data.tax_rate,
            amount_source=data.amount_source,
            by_shop=summary["by_shop"] if data.by_shop else {},
        )


async def fetch_sales_outbound_rows(
    obj: JushuitanConnectionModel,
    biz: dict[str, Any],
    max_rows: int = 20000,
    page_size: int = 50,
) -> list[dict]:
    """供元数据同步任务调用：按 ``biz``（含 modified_begin/modified_end）拉全量出库单。

    ``biz`` 里的 ``modified_begin``/``modified_end`` 为 ``yyyy-MM-dd HH:mm:ss``，
    超过 7 天时由客户端自动分段。
    """
    begin = datetime.strptime(str(biz.get("modified_begin", "")).strip(), TIME_FORMAT)
    end = datetime.strptime(str(biz.get("modified_end", "")).strip(), TIME_FORMAT)
    extra = {
        key: value
        for key, value in biz.items()
        if key not in {"modified_begin", "modified_end", "page_index", "page_size", "is_get_total"}
    }
    extra.setdefault("date_type", DATE_TYPE_IO_DATE)
    extra.setdefault("status", STATUS_CONFIRMED)
    rows: list[dict] = []
    async with build_client(obj) as client:
        async for row in client.iter_sales_outbound(begin, end, page_size=page_size, **extra):
            rows.append(row)
            if len(rows) >= max_rows:
                break
    return rows


def build_client(obj: JushuitanConnectionModel) -> JushuitanClient:
    """按连接配置（解密后）构造聚水潭客户端。"""
    return JushuitanService._client_from(obj)
