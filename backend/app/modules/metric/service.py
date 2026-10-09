import re

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.modules.masterdata.model import MasterDeptModel, MasterOrgModel
from app.utils.common_util import search_to_dict

from .batch import run_metric_batch
from .crud import MetricDefCRUD, MetricValueCRUD
from .engine import execute_metric_calc
from .model import MetricDefModel, MetricValueModel
from .schema import (
    MetricBatchResultSchema,
    MetricBatchRunRequestSchema,
    MetricCalcRequestSchema,
    MetricCalcResultSchema,
    MetricDefCreateSchema,
    MetricDefOutSchema,
    MetricDefQueryParam,
    MetricDefUpdateSchema,
    MetricMatrixColumnSchema,
    MetricMatrixQueryParam,
    MetricMatrixResultSchema,
    MetricMatrixRowSchema,
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
                search_dict["person_code"] = ("None", True)
            elif level == "dept":
                search_dict["dept_code"] = ("not None", True)
                search_dict["person_code"] = ("None", True)
            elif level == "person":
                search_dict["person_code"] = ("not None", True)

        result = await MetricValueCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"org_id": "asc"}, {"dept_id": "asc"}],
            search=search_dict,
            out_schema=MetricValueOutSchema,
        )
        await self._fill_master_names(result.items)
        return result

    async def _fill_master_names(self, items: list) -> None:
        """把组织/核算维度的主数据编码与名称补到结果行上（就地修改）。"""
        org_ids = {item.org_id for item in items if getattr(item, "org_id", None)}
        dept_ids = {item.dept_id for item in items if getattr(item, "dept_id", None)}
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
        for item in items:
            if item.org_id in org_names:
                item.org_code, item.org_name = org_names[item.org_id]
            # 业务员行的 dept_id 指向 master_person，不能拿 master_dept 的名称覆盖
            if getattr(item, "person_code", None):
                continue
            if item.dept_id in dept_names:
                item.dept_name = dept_names[item.dept_id]

    async def matrix(self, search: MetricMatrixQueryParam) -> MetricMatrixResultSchema:
        """指标表单查询：多个指标在同一期间 / 组织维度上并排展示，一次看全。

        - 每个指标各取自己的**最新计算版本**（版本号各指标独立递增，不能共用一个值）。
        - 组织合计行（``dept_code`` 为空）与核算维度明细行按 ``level`` 过滤。
        - 行按「组织 → 组织合计行 → 明细行」排序；公司整体口径指标（无 ``org_id``）排在最后。
        """
        metric_ids = list(
            dict.fromkeys(
                int(item)
                for item in re.split(r"[,\s]+", str(search.metric_ids or ""))
                if item.strip().isdigit()
            )
        )
        if not metric_ids:
            raise CustomException(msg="请至少选择一个指标")

        defs = (
            await self.db.execute(
                select(MetricDefModel).where(
                    MetricDefModel.id.in_(metric_ids), MetricDefModel.is_deleted == false()
                )
            )
        ).scalars().all()
        def_map = {int(item.id): item for item in defs}
        columns = [
            MetricMatrixColumnSchema(
                metric_id=metric_id,
                code=str(def_map[metric_id].code),
                name=str(def_map[metric_id].name or def_map[metric_id].code),
                period_type=str(def_map[metric_id].period_type or "month"),
                description=def_map[metric_id].description,
            )
            for metric_id in metric_ids
            if metric_id in def_map
        ]
        if not columns:
            raise CustomException(msg="选择的指标不存在或已删除")

        period_value = (search.period_value or "").strip() or None
        # 每个指标按自身期间类型 + 自身最新计算版本取值
        version_map: dict[int, tuple[str, int]] = {}
        for column in columns:
            period_type = str(search.period_type or column.period_type)
            conditions = [
                MetricValueModel.metric_id == column.metric_id,
                MetricValueModel.period_type == period_type,
            ]
            if period_value:
                conditions.append(MetricValueModel.period_value == period_value)
            latest = (
                await self.db.execute(select(func.max(MetricValueModel.calc_version)).where(*conditions))
            ).scalars().first()
            if latest:
                version_map[column.metric_id] = (period_type, int(latest))

        page_no = max(int(search.page_no or 1), 1)
        page_size = max(int(search.page_size or 500), 1)
        if not version_map:
            return MetricMatrixResultSchema(
                columns=columns, items=[], page_no=page_no, page_size=page_size, total=0, has_next=False
            )

        filters = [
            or_(
                *[
                    and_(
                        MetricValueModel.metric_id == metric_id,
                        MetricValueModel.period_type == period_type,
                        MetricValueModel.calc_version == calc_version,
                    )
                    for metric_id, (period_type, calc_version) in version_map.items()
                ]
            )
        ]
        if period_value:
            filters.append(MetricValueModel.period_value == period_value)
        if search.org_id:
            filters.append(MetricValueModel.org_id == search.org_id)
        if search.level == "org":
            filters.append(MetricValueModel.dept_code.is_(None))
            filters.append(MetricValueModel.person_code.is_(None))
        elif search.level == "dept":
            filters.append(MetricValueModel.dept_code.is_not(None))
            filters.append(MetricValueModel.person_code.is_(None))
        elif search.level == "person":
            filters.append(MetricValueModel.person_code.is_not(None))

        values = (await self.db.execute(select(MetricValueModel).where(*filters))).scalars().all()
        row_map: dict[tuple[int | None, str | None, str | None], MetricMatrixRowSchema] = {}
        for item in values:
            key = (item.org_id, item.dept_code, item.person_code)
            row = row_map.get(key)
            if row is None:
                row = MetricMatrixRowSchema(
                    row_key=f"{item.org_id or 0}|{item.dept_code or ''}|{item.person_code or ''}",
                    period_value=str(item.period_value),
                    org_id=item.org_id,
                    dept_id=item.dept_id,
                    dept_code=item.dept_code,
                    dept_name=item.dept_name,
                    person_id=item.person_id,
                    person_code=item.person_code,
                    person_name=item.person_name,
                )
                row_map[key] = row
            metric_key = str(item.metric_id)
            row.values[metric_key] = round(float(item.value or 0), 4)
            row.calc_versions[metric_key] = int(item.calc_version or 1)
            row.calc_times[metric_key] = item.calc_time

        all_rows = sorted(
            row_map.values(),
            key=lambda row: (
                row.org_id is None,
                row.org_id or 0,
                row.person_code is not None,
                row.dept_code is not None,
                row.dept_code or "",
                row.person_code or "",
            ),
        )
        total = len(all_rows)
        start = (page_no - 1) * page_size
        items = all_rows[start : start + page_size]
        await self._fill_master_names(items)
        return MetricMatrixResultSchema(
            columns=columns,
            items=items,
            page_no=page_no,
            page_size=page_size,
            total=total,
            has_next=start + page_size < total,
        )

    async def run_batch(self, data: MetricBatchRunRequestSchema) -> MetricBatchResultSchema:
        """批量重算：按依赖分层执行（组成指标先算），支持「全部指标」与「勾选的指标」。"""
        codes = [str(code).strip() for code in (data.codes or []) if str(code).strip()]
        if data.metric_ids:
            rows = (
                await self.db.execute(
                    select(MetricDefModel.code).where(MetricDefModel.id.in_(list(data.metric_ids)))
                )
            ).scalars().all()
            codes.extend(str(code) for code in rows if code)
        codes = list(dict.fromkeys(codes))
        try:
            summary = await run_metric_batch(
                period_value=data.period_value,
                codes=codes or None,
                refresh=False,
                label="手动重算",
            )
        except ValueError as e:
            raise CustomException(msg=str(e)) from e
        return MetricBatchResultSchema(**summary)

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
