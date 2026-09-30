from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import JushuitanConnectionModel
from .schema import JushuitanConnectionCreateSchema, JushuitanConnectionUpdateSchema


class JushuitanConnectionCRUD(
    CRUDBase[JushuitanConnectionModel, JushuitanConnectionCreateSchema, JushuitanConnectionUpdateSchema]
):
    """聚水潭连接配置数据层。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=JushuitanConnectionModel, auth=auth, db=db)
