from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import (
    FieldMappingModel,
    MetaSyncJobModel,
    MetaSyncRunModel,
    SourceFieldModel,
    SourceObjectModel,
    SourceSystemModel,
    StandardEntityModel,
    StandardFieldModel,
)
from .schema import (
    FieldMappingCreateSchema,
    FieldMappingUpdateSchema,
    MetaSyncJobCreateSchema,
    MetaSyncJobUpdateSchema,
    SourceFieldCreateSchema,
    SourceFieldUpdateSchema,
    SourceObjectCreateSchema,
    SourceObjectUpdateSchema,
    SourceSystemCreateSchema,
    SourceSystemUpdateSchema,
    StandardEntityCreateSchema,
    StandardEntityUpdateSchema,
    StandardFieldCreateSchema,
    StandardFieldUpdateSchema,
)


class SourceSystemCRUD(CRUDBase[SourceSystemModel, SourceSystemCreateSchema, SourceSystemUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=SourceSystemModel, auth=auth, db=db)


class SourceObjectCRUD(CRUDBase[SourceObjectModel, SourceObjectCreateSchema, SourceObjectUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=SourceObjectModel, auth=auth, db=db)


class SourceFieldCRUD(CRUDBase[SourceFieldModel, SourceFieldCreateSchema, SourceFieldUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=SourceFieldModel, auth=auth, db=db)


class FieldMappingCRUD(CRUDBase[FieldMappingModel, FieldMappingCreateSchema, FieldMappingUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=FieldMappingModel, auth=auth, db=db)


class StandardFieldCRUD(CRUDBase[StandardFieldModel, StandardFieldCreateSchema, StandardFieldUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=StandardFieldModel, auth=auth, db=db)


class StandardEntityCRUD(CRUDBase[StandardEntityModel, StandardEntityCreateSchema, StandardEntityUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=StandardEntityModel, auth=auth, db=db)


class MetaSyncJobCRUD(CRUDBase[MetaSyncJobModel, MetaSyncJobCreateSchema, MetaSyncJobUpdateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=MetaSyncJobModel, auth=auth, db=db)


class MetaSyncRunCRUD(CRUDBase[MetaSyncRunModel, dict, dict]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=MetaSyncRunModel, auth=auth, db=db)
