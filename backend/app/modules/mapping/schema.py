from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema


class DeptMappingCreateSchema(BaseModel):
    source_dept_id: int = Field(..., ge=1, description="来源部门ID")
    master_dept_id: int = Field(..., ge=1, description="内部标准部门ID")
    match_mode: Literal["exact", "fuzzy", "manual"] = Field(default="manual", description="匹配方式")
    confidence: int = Field(default=100, ge=0, le=100, description="置信度")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:有效 1:失效)")


class DeptMappingUpdateSchema(DeptMappingCreateSchema):
    pass


class DeptMappingOutSchema(DeptMappingCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    source_type: str | None = Field(default=None, description="来源类型")
    source_org_code: str | None = Field(default=None, description="来源组织编码")
    source_dept_code: str | None = Field(default=None, description="来源部门编码")
    source_dept_name: str | None = Field(default=None, description="来源部门名称")
    master_org_code: str | None = Field(default=None, description="标准组织编码")
    master_dept_code: str | None = Field(default=None, description="标准部门编码")
    master_dept_name: str | None = Field(default=None, description="标准部门名称")


class DeptMappingQueryParam(BaseQueryParam, UserByQueryParam):
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})
    match_mode: Literal["exact", "fuzzy", "manual"] | None = Field(None, description="匹配方式", json_schema_extra={"q": "eq"})


class AutoMatchSchema(BaseModel):
    source_type: str | None = Field(default=None, max_length=32, description="来源类型；空表示全部")


class OrgBindSchema(BaseModel):
    source_org_id: int = Field(..., ge=1, description="来源组织ID")
    master_org_id: int = Field(..., ge=1, description="内部标准组织ID")


class DeptBindSchema(BaseModel):
    source_dept_id: int = Field(..., ge=1, description="来源部门ID")
    master_dept_id: int = Field(..., ge=1, description="内部标准部门ID")


class PersonBindSchema(BaseModel):
    source_person_id: int = Field(..., ge=1, description="来源人员ID")
    master_person_id: int = Field(..., ge=1, description="内部标准人员ID")


class PersonOrgBindSchema(BaseModel):
    source_person_id: int = Field(..., ge=1, description="来源人员ID")
    master_person_id: int = Field(..., ge=1, description="内部标准人员ID")
    master_org_id: int = Field(..., ge=1, description="内部标准组织ID")
    master_dept_id: int | None = Field(default=None, ge=1, description="内部标准部门ID")
    is_primary: bool = Field(default=False, description="是否主任岗")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:有效 1:失效)")


class MasterDeptOptionSchema(BaseModel):
    id: int = Field(description="部门ID")
    code: str = Field(description="部门编码")
    name: str = Field(description="部门名称")
    org_id: int = Field(description="组织ID")
    org_name: str | None = Field(default=None, description="组织名称")


class SysDeptBindSchema(BaseModel):
    sys_dept_id: int = Field(..., ge=1, description="系统权限部门ID")
    master_dept_ids: list[int] = Field(..., min_length=1, description="业务标准部门ID列表")


class SysDeptUnbindSchema(BaseModel):
    sys_dept_id: int = Field(..., ge=1, description="系统权限部门ID")
    master_dept_ids: list[int] = Field(..., min_length=1, description="业务标准部门ID列表")


class SysDeptBusinessMappingOutSchema(BaseModel):
    id: int = Field(description="绑定ID")
    sys_dept_id: int = Field(description="系统权限部门ID")
    sys_dept_code: str | None = Field(default=None, description="系统权限部门编码")
    sys_dept_name: str | None = Field(default=None, description="系统权限部门名称")
    master_dept_id: int = Field(description="业务标准部门ID")
    master_dept_code: str | None = Field(default=None, description="业务标准部门编码")
    master_dept_name: str | None = Field(default=None, description="业务标准部门名称")
    source_type: str | None = Field(default=None, description="来源类型")
    source_org_code: str | None = Field(default=None, description="来源组织编码")
    source_dept_code: str | None = Field(default=None, description="来源部门编码")
    status: int = Field(description="状态")


class MasterDeptBusinessOptionSchema(BaseModel):
    id: int = Field(description="业务标准部门ID")
    code: str = Field(description="业务标准部门编码")
    name: str = Field(description="业务标准部门名称")
    org_id: int = Field(description="组织ID")
    org_code: str | None = Field(default=None, description="组织编码")
    org_name: str | None = Field(default=None, description="组织名称")
    source_type: str | None = Field(default=None, description="来源类型")
    source_org_code: str | None = Field(default=None, description="来源组织编码")
    source_dept_code: str | None = Field(default=None, description="来源部门编码")
