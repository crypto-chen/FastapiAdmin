from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.modules.masterdata.model import MasterDeptModel, MasterOrgModel
from app.utils.common_util import search_to_dict

from .crud import MetricDefCRUD, MetricValueCRUD
from .engine import execute_metric_calc
from .model import MetricDefModel, MetricValueModel
from .schema import (
    MetricCalcRequestSchema,
    MetricCalcResultSchema,
    MetricDefCreateSchema,
    MetricDefOutSchema,
    MetricDefQueryParam,
    MetricDefUpdateSchema,
    MetricValueOutSchema,
    MetricValueQueryParam,
)


class MetricService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def _to_out(self, obj: MetricDefModel) -> MetricDefOutSchema:
        out = MetricDefOutSchema.model_validate(obj)
        if obj.source_entity_id:
            from app.modules.metadata.model import StandardEntityModel

            entity = await self.db.get(StandardEntityModel, obj.source_entity_id)
            out.source_entity_code = entity.code if entity else None
            out.source_entity_name = entity.name if entity else None
        return out

    async def page(self, search: MetricDefQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[MetricDefOutSchema]:
        result = await MetricDefCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "desc"}], search=search_to_dict(search)
        )
        return PageResultSchema[MetricDefOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[await self._to_out(obj) for obj in result.items],
        )

    async def detail(self, id: int) -> MetricDefOutSchema:
        obj = await MetricDefCRUD(self.auth, self.db).get_or_404(id=id, msg="该指标不存在")
        return await self._to_out(obj)

    async def create(self, data: MetricDefCreateSchema) -> MetricDefOutSchema:
        if await MetricDefCRUD(self.auth, self.db).get(code=data.code):
            raise CustomException(msg="创建失败，指标编码已存在")
        if data.source_entity_id:
            from app.modules.metadata.model import StandardEntityModel

            if await self.db.get(StandardEntityModel, data.source_entity_id) is None:
                raise CustomException(msg="来源标准实体不存在")
        obj = await MetricDefCRUD(self.auth, self.db).create(data=data)
        return await self.detail(obj.id)

    async def update(self, id: int, data: MetricDefUpdateSchema) -> MetricDefOutSchema:
        await MetricDefCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该指标不存在")
        exist = await MetricDefCRUD(self.auth, self.db).get(code=data.code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，指标编码已存在")
        await MetricDefCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail(id)

    async def delete(self, ids: list[int]) -> None:
        await MetricDefCRUD(self.auth, self.db).delete(ids=ids)

    async def page_value(
        self, search: MetricValueQueryParam | None, page_no: int, page_size: int
    ) -> PageResultSchema[MetricValueOutSchema]:
        """分页查询指标结果；未指定 ``calc_version`` 时默认取最新计算版本。"""
        if search is not None and search.calc_version is None and search.metric_id:
            conditions = [MetricValueModel.metric_id == search.metric_id]
            if search.period_type:
                conditions.append(MetricValueModel.period_type == search.period_type)
            if search.period_value:
                conditions.append(MetricValueModel.period_value == search.period_value)
            latest = (
                await self.db.execute(select(func.max(MetricValueModel.calc_version)).where(*conditions))
            ).scalars().first()
            if latest:
                search.calc_version = int(latest)

        search_dict = search_to_dict(search) or {}
        # level 由服务层翻译成「核算维度编码」的 IS NULL / IS NOT NULL 条件：
        # 未映射到 master_dept 的维度行也要算明细行，否则会被当成组织合计重复计入
        level = search_dict.pop("level", "org")
        if (search is None or search.dept_id is None):
            if level == "org":
                search_dict["dept_code"] = ("None", True)
            elif level == "dept":
                search_dict["dept_code"] = ("not None", True)

        result = await MetricValueCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"org_id": "asc"}, {"dept_id": "asc"}],
            search=search_dict,
            out_schema=MetricValueOutSchema,
        )
        org_ids = {item.org_id for item in result.items if item.org_id}
        dept_ids = {item.dept_id for item in result.items if item.dept_id}
        org_names: dict[int, tuple[str, str]] = {}
        if org_ids:
            rows = (
                await self.db.execute(
                    select(MasterOrgModel.id, MasterOrgModel.code, MasterOrgModel.name).where(
                        MasterOrgModel.id.in_(org_ids)
                    )
                )
            ).all()
            org_names = {row[0]: (row[1], row[2]) for row in rows}
        dept_names: dict[int, str] = {}
        if dept_ids:
            rows = (
                await self.db.execute(
                    select(MasterDeptModel.id, MasterDeptModel.name).where(MasterDeptModel.id.in_(dept_ids))
                )
            ).all()
            dept_names = {row[0]: row[1] for row in rows}
        for item in result.items:
            if item.org_id in org_names:
                item.org_code, item.org_name = org_names[item.org_id]
            if item.dept_id in dept_names:
                item.dept_name = dept_names[item.dept_id]
        return result

    async def run_calc(self, id: int, data: MetricCalcRequestSchema | None) -> MetricCalcResultSchema:
        """手动重算指标（按期间 / 按组织），口径与定时任务完全一致。"""
        await MetricDefCRUD(self.auth, self.db).get_or_404(id=id, msg="该指标不存在")
        payload = data or MetricCalcRequestSchema()
        try:
            summary = await execute_metric_calc(
                metric_id=id, period_value=payload.period_value, org_codes=payload.org_codes
            )
        except ValueError as e:
            raise CustomException(msg=str(e)) from e
        return MetricCalcResultSchema(**summary)
