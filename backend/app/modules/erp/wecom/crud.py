"""企业微信连接配置数据层。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import WeComConnectionModel
from .schema import WeComConnectionCreateSchema, WeComConnectionUpdateSchema


class WeComConnectionCRUD(
    CRUDBase[WeComConnectionModel, WeComConnectionCreateSchema, WeComConnectionUpdateSchema]
):
    """企业微信连接配置 CRUD。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=WeComConnectionModel, auth=auth, db=db)

