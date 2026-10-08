
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema
from app.core.validator import DateTimeStr


class MetaVariableSchema(BaseModel):
    """参数变量定义。"""

    name: str = Field(..., min_length=1, max_length=64, description="变量名")
    value_type: Literal["string", "integer", "decimal", "boolean", "date", "json", "expression"] = Field(
        default="string", description="变量值类型"
    )
    value: object = Field(default=None, description="变量值")
    description: str | None = Field(default=None, max_length=255, description="说明")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("变量名不能为空")
        return value


class SourceSystemCreateSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, description="系统编码")
    name: str = Field(..., min_length=1, max_length=128, description="系统名称")
    connector_type: str = Field(..., min_length=1, max_length=32, description="连接器类型")
    connection_id: int | None = Field(default=None, ge=1, description="连接配置ID")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("code", "name", "connector_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("编码、名称、连接器类型不能为空")
        return value


class SourceSystemUpdateSchema(SourceSystemCreateSchema):
    pass


class SourceSystemOutSchema(SourceSystemCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)


class SourceSystemQueryParam(BaseQueryParam, UserByQueryParam):
    name: str | None = Field(None, description="系统名称", json_schema_extra={"q": "like"})
    code: str | None = Field(None, description="系统编码", json_schema_extra={"q": "like"})
    connector_type: str | None = Field(None, description="连接器类型", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class SourceObjectCreateSchema(BaseModel):
    system_id: int = Field(..., ge=1, description="来源系统ID")
    code: str = Field(..., min_length=1, max_length=128, description="对象编码/表单Id")
    name: str = Field(..., min_length=1, max_length=255, description="对象名称")
    query_type: str = Field(default="bill_query", min_length=1, max_length=32, description="查询类型")
    request_template: dict | None = Field(default=None, description="请求模板")
    variables: list[MetaVariableSchema] | None = Field(default=None, description="变量定义列表")
    watermark_field: str | None = Field(default=None, max_length=128, description="增量水位字段")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")

    @field_validator("code", "name", "query_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("编码、名称、查询类型不能为空")
        return value


class SourceObjectUpdateSchema(SourceObjectCreateSchema):
    pass


class SourceObjectOutSchema(SourceObjectCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    system_code: str | None = Field(default=None, description="系统编码")
    system_name: str | None = Field(default=None, description="系统名称")


class SourceObjectQueryParam(BaseQueryParam, UserByQueryParam):
    system_id: int | None = Field(None, description="来源系统ID", json_schema_extra={"q": "eq"})
    code: str | None = Field(None, description="对象编码", json_schema_extra={"q": "like"})
    name: str | None = Field(None, description="对象名称", json_schema_extra={"q": "like"})
    query_type: str | None = Field(None, description="查询类型", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class SourceFieldCreateSchema(BaseModel):
    object_id: int = Field(..., ge=1, description="来源对象ID")
    field_key: str = Field(..., min_length=1, max_length=128, description="字段Key")
    field_name: str = Field(..., min_length=1, max_length=255, description="字段名称")
    data_type: str = Field(default="string", min_length=1, max_length=32, description="数据类型")
    is_primary_key: bool = Field(default=False, description="是否主键")
    is_watermark: bool = Field(default=False, description="是否增量水位")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")

    @field_validator("field_key", "field_name", "data_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段Key、名称、数据类型不能为空")
        return value


class SourceFieldUpdateSchema(SourceFieldCreateSchema):
    pass


class SourceFieldOutSchema(SourceFieldCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    object_code: str | None = Field(default=None, description="对象编码")
    object_name: str | None = Field(default=None, description="对象名称")


class SourceFieldQueryParam(BaseQueryParam, UserByQueryParam):
    object_id: int | None = Field(None, description="来源对象ID", json_schema_extra={"q": "eq"})
    field_key: str | None = Field(None, description="字段Key", json_schema_extra={"q": "like"})
    field_name: str | None = Field(None, description="字段名称", json_schema_extra={"q": "like"})
    data_type: str | None = Field(None, description="数据类型", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class FieldMappingCreateSchema(BaseModel):
    source_object_id: int = Field(..., ge=1, description="来源对象ID")
    source_field_id: int = Field(..., ge=1, description="来源字段ID")
    standard_field_id: int = Field(..., ge=1, description="标准字段ID")
    transform_type: str = Field(default="direct", min_length=1, max_length=32, description="加工类型")
    transform_config: dict | None = Field(default=None, description="加工配置")
    order: int = Field(default=0, ge=0, description="执行顺序")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")

    @field_validator("transform_type")
    @classmethod
    def strip_transform_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("加工类型不能为空")
        return value


class FieldMappingUpdateSchema(FieldMappingCreateSchema):
    pass


class FieldMappingOutSchema(FieldMappingCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    source_field_key: str | None = Field(default=None, description="来源字段Key")
    source_field_name: str | None = Field(default=None, description="来源字段名称")
    standard_field_code: str | None = Field(default=None, description="标准字段编码")
    standard_field_name: str | None = Field(default=None, description="标准字段名称")


class FieldMappingQueryParam(BaseQueryParam, UserByQueryParam):
    source_object_id: int | None = Field(None, description="来源对象ID", json_schema_extra={"q": "eq"})
    source_field_id: int | None = Field(None, description="来源字段ID", json_schema_extra={"q": "eq"})
    standard_field_id: int | None = Field(None, description="标准字段ID", json_schema_extra={"q": "eq"})
    transform_type: str | None = Field(None, description="加工类型", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class StandardEntityCreateSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, description="标准实体编码")
    name: str = Field(..., min_length=1, max_length=255, description="标准实体名称")
    table_name: str | None = Field(default=None, max_length=128, description="目标物理表")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("code", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("编码和名称不能为空")
        return value


class StandardEntityUpdateSchema(StandardEntityCreateSchema):
    pass


class StandardEntityOutSchema(StandardEntityCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)


class StandardEntityQueryParam(BaseQueryParam, UserByQueryParam):
    code: str | None = Field(None, description="标准实体编码", json_schema_extra={"q": "like"})
    name: str | None = Field(None, description="标准实体名称", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class StandardFieldCreateSchema(BaseModel):
    entity_id: int = Field(..., ge=1, description="标准实体ID")
    field_code: str = Field(..., min_length=1, max_length=128, description="标准字段编码")
    field_name: str = Field(..., min_length=1, max_length=255, description="标准字段名称")
    data_type: str = Field(default="string", min_length=1, max_length=32, description="数据类型")
    is_dimension: bool = Field(default=False, description="是否维度")
    is_measure: bool = Field(default=False, description="是否度量")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")

    @field_validator("field_code", "field_name", "data_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段编码、名称、数据类型不能为空")
        return value


class StandardFieldUpdateSchema(StandardFieldCreateSchema):
    pass


class StandardFieldOutSchema(StandardFieldCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    entity_code: str | None = Field(default=None, description="标准实体编码")
    entity_name: str | None = Field(default=None, description="标准实体名称")


class StandardFieldQueryParam(BaseQueryParam, UserByQueryParam):
    entity_id: int | None = Field(None, description="标准实体ID", json_schema_extra={"q": "eq"})
    field_code: str | None = Field(None, description="标准字段编码", json_schema_extra={"q": "like"})
    field_name: str | None = Field(None, description="标准字段名称", json_schema_extra={"q": "like"})
    data_type: str | None = Field(None, description="数据类型", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class MetaSyncJobBaseSchema(BaseModel):
    """同步任务公共字段。

    输出模型复用本类：写入侧强制 Cron 非空，但读侧必须容忍历史空值
    （``meta_sync_job.cron_expr`` 是 nullable=False 且无默认值，历史数据里
    存在空字符串，曾导致 ``GET /metadata/sync-job/page`` 直接 400）。
    """

    name: str = Field(..., min_length=1, max_length=128, description="任务名称")
    source_system_id: int = Field(..., ge=1, description="来源系统ID")
    source_object_id: int = Field(..., ge=1, description="来源对象ID")
    standard_entity_id: int | None = Field(default=None, ge=1, description="标准实体ID")
    org_code: str | None = Field(default=None, max_length=64, description="组织编码")
    cron_expr: str = Field(default="", max_length=64, description="Cron表达式（空表示未配置，任务不会被调度）")
    request_params: dict | None = Field(default=None, description="请求参数/Model")
    variables: list[MetaVariableSchema] | None = Field(default=None, description="任务级变量定义")
    sync_mode: str = Field(default="full", min_length=1, max_length=16, description="同步模式")
    watermark_field: str | None = Field(default=None, max_length=128, description="增量水位字段")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")


class MetaSyncJobCreateSchema(MetaSyncJobBaseSchema):
    """新增同步任务：Cron 必填且非空（空 Cron 的任务不会被注册进调度器）。"""

    cron_expr: str = Field(..., min_length=1, max_length=64, description="Cron表达式")

    @field_validator("name", "cron_expr")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("任务名称和Cron表达式不能为空")
        return value


class MetaSyncJobUpdateSchema(MetaSyncJobCreateSchema):
    pass


class MetaSyncJobOutSchema(MetaSyncJobBaseSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    system_code: str | None = Field(default=None, description="来源系统编码")
    object_code: str | None = Field(default=None, description="来源对象编码")
    object_name: str | None = Field(default=None, description="来源对象名称")


class MetaSyncJobQueryParam(BaseQueryParam, UserByQueryParam):
    name: str | None = Field(None, description="任务名称", json_schema_extra={"q": "like"})
    source_system_id: int | None = Field(None, description="来源系统ID", json_schema_extra={"q": "eq"})
    source_object_id: int | None = Field(None, description="来源对象ID", json_schema_extra={"q": "eq"})
    org_code: str | None = Field(None, description="组织编码", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class MetaSyncRunOutSchema(BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    job_id: int = Field(description="任务ID")
    batch_id: str | None = Field(default=None, description="批次ID")
    status: str = Field(description="状态")
    row_count: int = Field(default=0, description="行数")
    started_at: DateTimeStr | None = Field(default=None, description="开始时间")
    finished_at: DateTimeStr | None = Field(default=None, description="结束时间")
    error: str | None = Field(default=None, description="错误信息")


class MetaSyncRunDetailSchema(MetaSyncRunOutSchema):
    rows_json: dict | None = Field(default=None, description="原始返回数据")
