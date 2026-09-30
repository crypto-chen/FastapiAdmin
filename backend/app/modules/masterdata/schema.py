from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema


class MasterOrgCreateSchema(BaseModel):
    """内部标准组织创建模型。"""

    code: str = Field(..., min_length=1, max_length=64, description="组织编码")
    name: str = Field(..., min_length=1, max_length=128, description="组织名称")
    parent_id: int | None = Field(default=None, ge=1, description="上级组织ID")
    order: int = Field(default=999, ge=0, description="显示排序")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("code", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("编码和名称不能为空")
        return value


class MasterOrgUpdateSchema(MasterOrgCreateSchema):
    """内部标准组织更新模型。"""


class MasterOrgOutSchema(MasterOrgCreateSchema, BaseSchema, UserBySchema):
    """内部标准组织输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    parent_name: str | None = Field(default=None, max_length=128, description="上级组织名称")


class MasterOrgTreeOutSchema(MasterOrgOutSchema):
    """内部标准组织树输出模型。"""

    children: list["MasterOrgTreeOutSchema"] | None = Field(default=None, description="子组织列表")


class MasterOrgQueryParam(BaseQueryParam, UserByQueryParam):
    """内部标准组织查询参数。"""

    name: str | None = Field(None, description="组织名称", json_schema_extra={"q": "like"})
    code: str | None = Field(None, description="组织编码", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态(0:启用 1:停用)", json_schema_extra={"q": "eq"})


class MasterPersonCreateSchema(BaseModel):
    """内部标准人员创建模型。"""

    code: str = Field(..., min_length=1, max_length=64, description="人员编码")
    name: str = Field(..., min_length=1, max_length=128, description="人员姓名")
    org_id: int | None = Field(default=None, ge=1, description="所属组织ID")
    mobile: str | None = Field(default=None, max_length=32, description="手机号")
    email: str | None = Field(default=None, max_length=128, description="邮箱")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("code", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("编码和姓名不能为空")
        return value


class MasterPersonUpdateSchema(MasterPersonCreateSchema):
    """内部标准人员更新模型。"""


class MasterPersonOutSchema(MasterPersonCreateSchema, BaseSchema, UserBySchema):
    """内部标准人员输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    org_name: str | None = Field(default=None, max_length=128, description="所属组织名称")


class MasterPersonQueryParam(BaseQueryParam, UserByQueryParam):
    """内部标准人员查询参数。"""

    name: str | None = Field(None, description="人员姓名", json_schema_extra={"q": "like"})
    code: str | None = Field(None, description="人员编码", json_schema_extra={"q": "like"})
    org_id: int | None = Field(None, description="所属组织ID", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态(0:启用 1:停用)", json_schema_extra={"q": "eq"})


class SourceOrgOutSchema(BaseSchema, UserBySchema):
    """来源组织输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    source_type: str = Field(description="来源类型")
    source_code: str = Field(description="来源组织编码")
    source_name: str = Field(description="来源组织名称")
    source_parent_code: str | None = Field(default=None, description="来源上级编码")
    raw_json: dict | None = Field(default=None, description="原始数据")
    status: int = Field(description="状态(0:有效 1:停用)")


class SourcePersonOutSchema(BaseSchema, UserBySchema):
    """来源人员输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    source_type: str = Field(description="来源类型")
    source_code: str = Field(description="来源人员编码")
    source_name: str = Field(description="来源人员姓名")
    source_org_code: str | None = Field(default=None, description="来源组织编码")
    mobile: str | None = Field(default=None, description="手机号")
    email: str | None = Field(default=None, description="邮箱")
    raw_json: dict | None = Field(default=None, description="原始数据")
    status: int = Field(description="状态(0:有效 1:停用)")


class SourceQueryParam(BaseQueryParam, UserByQueryParam):
    """来源数据通用查询参数。"""

    source_type: str | None = Field(None, description="来源类型", json_schema_extra={"q": "eq"})
    source_code: str | None = Field(None, description="来源编码", json_schema_extra={"q": "like"})
    source_name: str | None = Field(None, description="来源名称", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态(0:有效 1:停用)", json_schema_extra={"q": "eq"})


class OrgMappingCreateSchema(BaseModel):
    """组织映射创建模型。"""

    source_org_id: int = Field(..., ge=1, description="来源组织ID")
    master_org_id: int = Field(..., ge=1, description="内部标准组织ID")
    match_mode: Literal["exact", "fuzzy", "manual"] = Field(default="manual", description="匹配方式")
    confidence: int = Field(default=100, ge=0, le=100, description="匹配置信度")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:有效 1:失效)")


class OrgMappingUpdateSchema(OrgMappingCreateSchema):
    """组织映射更新模型。"""


class OrgMappingOutSchema(OrgMappingCreateSchema, BaseSchema, UserBySchema):
    """组织映射输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    source_type: str | None = Field(default=None, description="来源类型")
    source_org_code: str | None = Field(default=None, description="来源组织编码")
    source_org_name: str | None = Field(default=None, description="来源组织名称")
    master_org_code: str | None = Field(default=None, description="内部组织编码")
    master_org_name: str | None = Field(default=None, description="内部组织名称")


class PersonMappingCreateSchema(BaseModel):
    """人员映射创建模型。"""

    source_person_id: int = Field(..., ge=1, description="来源人员ID")
    master_person_id: int = Field(..., ge=1, description="内部标准人员ID")
    match_mode: Literal["exact", "fuzzy", "manual"] = Field(default="manual", description="匹配方式")
    confidence: int = Field(default=100, ge=0, le=100, description="匹配置信度")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:有效 1:失效)")


class PersonMappingUpdateSchema(PersonMappingCreateSchema):
    """人员映射更新模型。"""


class PersonMappingOutSchema(PersonMappingCreateSchema, BaseSchema, UserBySchema):
    """人员映射输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    source_type: str | None = Field(default=None, description="来源类型")
    source_person_code: str | None = Field(default=None, description="来源人员编码")
    source_person_name: str | None = Field(default=None, description="来源人员姓名")
    master_person_code: str | None = Field(default=None, description="内部人员编码")
    master_person_name: str | None = Field(default=None, description="内部人员姓名")


class MappingQueryParam(BaseQueryParam, UserByQueryParam):
    """映射查询参数。"""

    status: int | None = Field(None, ge=0, le=1, description="状态(0:有效 1:失效)", json_schema_extra={"q": "eq"})
    match_mode: Literal["exact", "fuzzy", "manual"] | None = Field(None, description="匹配方式", json_schema_extra={"q": "eq"})


class AutoMatchSchema(BaseModel):
    """自动匹配请求。"""

    source_type: str | None = Field(default=None, max_length=32, description="来源类型；空表示全部")
