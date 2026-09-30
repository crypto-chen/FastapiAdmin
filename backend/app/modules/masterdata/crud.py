from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import (
    MasterOrgModel,
    MasterPersonModel,
    OrgMappingModel,
    PersonMappingModel,
    SourceOrgModel,
    SourcePersonModel,
)
from .schema import (
    MasterOrgCreateSchema,
    MasterOrgUpdateSchema,
    MasterPersonCreateSchema,
    MasterPersonUpdateSchema,
    OrgMappingCreateSchema,
    OrgMappingUpdateSchema,
    PersonMappingCreateSchema,
    PersonMappingUpdateSchema,
)


class MasterOrgCRUD(CRUDBase[MasterOrgModel, MasterOrgCreateSchema, MasterOrgUpdateSchema]):
    """内部标准组织数据层。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=MasterOrgModel, auth=auth, db=db)


class MasterPersonCRUD(CRUDBase[MasterPersonModel, MasterPersonCreateSchema, MasterPersonUpdateSchema]):
    """内部标准人员数据层。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=MasterPersonModel, auth=auth, db=db)


class SourceOrgCRUD(CRUDBase[SourceOrgModel, dict, dict]):
    """来源组织数据层（只读为主）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=SourceOrgModel, auth=auth, db=db)


class SourcePersonCRUD(CRUDBase[SourcePersonModel, dict, dict]):
    """来源人员数据层（只读为主）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=SourcePersonModel, auth=auth, db=db)


class OrgMappingCRUD(CRUDBase[OrgMappingModel, OrgMappingCreateSchema, OrgMappingUpdateSchema]):
    """组织映射数据层。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=OrgMappingModel, auth=auth, db=db)


class PersonMappingCRUD(CRUDBase[PersonMappingModel, PersonMappingCreateSchema, PersonMappingUpdateSchema]):
    """人员映射数据层。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=PersonMappingModel, auth=auth, db=db)
