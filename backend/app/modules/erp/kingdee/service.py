from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.utils.common_util import search_to_dict
from app.utils.crypto_util import CryptoUtil

from .client import KingdeeBillQueryRequest, KingdeeClient, KingdeeClientConfig
from .crud import KingdeeConnectionCRUD
from .model import KingdeeConnectionModel
from .schema import (
    KingdeeBillQueryResultSchema,
    KingdeeBillQuerySchema,
    KingdeeConnectionCreateSchema,
    KingdeeConnectionOutSchema,
    KingdeeConnectionQueryParam,
    KingdeeConnectionUpdateSchema,
    KingdeeViewSchema,
)


class KingdeeService:
    """金蝶连接配置与查询服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _crud(self) -> KingdeeConnectionCRUD:
        return KingdeeConnectionCRUD(self.auth, self.db)

    @staticmethod
    def _to_out(obj: KingdeeConnectionModel) -> KingdeeConnectionOutSchema:
        out = KingdeeConnectionOutSchema.model_validate(obj)
        out.has_secret = bool(obj.app_secret)
        return out

    @staticmethod
    def _client_from(obj: KingdeeConnectionModel) -> KingdeeClient:
        secret = CryptoUtil.decrypt(obj.app_secret) if obj.app_secret else ""
        return KingdeeClient(
            KingdeeClientConfig(
                server_url=obj.server_url,
                acct_id=obj.acct_id,
                username=obj.username,
                app_id=obj.app_id,
                app_secret=secret,
                lcid=obj.lcid,
                org_num=obj.org_num,
                connect_timeout=obj.connect_timeout,
                request_timeout=obj.request_timeout,
                proxy=obj.proxy or "",
            )
        )

    async def detail(self, id: int) -> KingdeeConnectionOutSchema:
        obj = await self._crud().get_or_404(id=id, msg="该金蝶连接不存在")
        return self._to_out(obj)

    async def get_list(self, search: KingdeeConnectionQueryParam | None = None) -> list[KingdeeConnectionOutSchema]:
        objs = await self._crud().get_list(search=search_to_dict(search), order_by=[{"id": "asc"}])
        return [self._to_out(obj) for obj in objs]

    async def page(
        self,
        search: KingdeeConnectionQueryParam | None,
        page_no: int,
        page_size: int,
        order_by: list[dict] | None = None,
    ) -> PageResultSchema[KingdeeConnectionOutSchema]:
        result = await self._crud().page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=order_by or [{"id": "asc"}],
            search=search_to_dict(search),
        )
        return PageResultSchema[KingdeeConnectionOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=[self._to_out(obj) for obj in result.items],
        )

    async def create(self, data: KingdeeConnectionCreateSchema) -> KingdeeConnectionOutSchema:
        if await self._crud().get(name=data.name):
            raise CustomException(msg="创建失败，连接名称已存在")
        payload = data.model_dump(exclude_none=True)
        if payload.get("app_secret"):
            payload["app_secret"] = CryptoUtil.encrypt(payload["app_secret"])
        obj = await self._crud().create(data=payload)
        return self._to_out(obj)

    async def update(self, id: int, data: KingdeeConnectionUpdateSchema) -> KingdeeConnectionOutSchema:
        await self._crud().get_or_404(id=id, msg="更新失败，该金蝶连接不存在")
        exist = await self._crud().get(name=data.name)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，连接名称已存在")

        payload = data.model_dump(exclude_unset=True)
        if payload.get("app_secret"):
            payload["app_secret"] = CryptoUtil.encrypt(payload["app_secret"])
        else:
            payload.pop("app_secret", None)
        await self._crud().update(id=id, data=payload)
        obj = await self._crud().get_or_404(id=id)
        return self._to_out(obj)

    async def delete(self, ids: list[int]) -> None:
        if not ids:
            raise CustomException(msg="删除失败，删除对象不能为空")
        await self._crud().delete(ids=ids)

    async def test_connection(self, id: int) -> bool:
        obj = await self._crud().get_or_404(id=id, msg="该金蝶连接不存在")
        if obj.status == 1:
            raise CustomException(msg="该金蝶连接已停用")
        try:
            return await self._client_from(obj).test_connection()
        except Exception as e:
            raise CustomException(msg=f"连接失败：{e}") from e

    async def bill_query(self, data: KingdeeBillQuerySchema) -> KingdeeBillQueryResultSchema:
        obj = await self._crud().get_or_404(id=data.source_id, msg="该金蝶连接不存在")
        if obj.status == 1:
            raise CustomException(msg="该金蝶连接已停用")
        request = KingdeeBillQueryRequest(
            form_id=data.form_id,
            field_keys=data.field_keys,
            filter_string=data.filter_string,
            order_string=data.order_string,
            top_row_count=data.top_row_count,
            start_row=data.start_row,
            limit=data.limit,
        )
        try:
            fields, items = await self._client_from(obj).bill_query(request)
        except Exception as e:
            raise CustomException(msg=f"查询失败：{e}") from e
        return KingdeeBillQueryResultSchema(
            source_id=data.source_id,
            form_id=data.form_id,
            fields=fields,
            row_count=len(items),
            items=items,
        )

    async def view(self, data: KingdeeViewSchema) -> dict:
        obj = await self._crud().get_or_404(id=data.source_id, msg="该金蝶连接不存在")
        if obj.status == 1:
            raise CustomException(msg="该金蝶连接已停用")
        try:
            return await self._client_from(obj).view(data.form_id, data.data)
        except Exception as e:
            raise CustomException(msg=f"查看失败：{e}") from e
