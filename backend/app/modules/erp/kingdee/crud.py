from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import KingdeeConnectionModel
from .schema import KingdeeConnectionCreateSchema, KingdeeConnectionUpdateSchema


class KingdeeConnectionCRUD(CRUDBase[KingdeeConnectionModel, KingdeeConnectionCreateSchema, KingdeeConnectionUpdateSchema]):
    """金蝶连接配置数据层。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=KingdeeConnectionModel, auth=auth, db=db)
