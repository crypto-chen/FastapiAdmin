from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import MetricDefModel, MetricValueModel
from .schema import MetricDefCreateSchema, MetricDefUpdateSchema


class MetricDefCRUD(CRUDBase[MetricDefModel, MetricDefCreateSchema, MetricDefUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=MetricDefModel, auth=auth, db=db)


class MetricValueCRUD(CRUDBase[MetricValueModel, MetricDefCreateSchema, MetricDefUpdateSchema]):
    """指标结果查询（只读使用，创建/更新由计算引擎直接落库）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=MetricValueModel, auth=auth, db=db)
