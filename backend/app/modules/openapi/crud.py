from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import OpenApiLogModel, OpenClientModel
from .schema import OpenClientCreateSchema, OpenClientUpdateSchema


class OpenClientCRUD(CRUDBase[OpenClientModel, OpenClientCreateSchema, OpenClientUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=OpenClientModel, auth=auth, db=db)


class OpenApiLogCRUD(CRUDBase[OpenApiLogModel, dict, dict]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=OpenApiLogModel, auth=auth, db=db)
