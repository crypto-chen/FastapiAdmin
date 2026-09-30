from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema


class KingdeeConnectionCreateSchema(BaseModel):
    """金蝶连接配置创建模型。"""

    name: str = Field(..., min_length=1, max_length=64, description="连接名称")
    server_url: str = Field(..., min_length=1, max_length=512, description="服务地址(以 /k3cloud/ 结尾)")
    acct_id: str = Field(..., min_length=1, max_length=128, description="账套ID")
    username: str = Field(..., min_length=1, max_length=128, description="授权用户")
    app_id: str = Field(..., min_length=1, max_length=255, description="应用ID")
    app_secret: str | None = Field(default=None, max_length=512, description="应用密钥")
    lcid: int = Field(default=2052, description="账套语系")
    org_num: int = Field(default=0, ge=0, description="组织编码(多组织时启用)")
    connect_timeout: int = Field(default=120, ge=1, le=600, description="连接超时(秒)")
    request_timeout: int = Field(default=120, ge=1, le=3600, description="读取超时(秒)")
    proxy: str | None = Field(default=None, max_length=255, description="代理地址")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("name", "server_url", "acct_id", "username", "app_id")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("必填项不能为空")
        return value

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("服务地址必须以 http:// 或 https:// 开头")
        return value


class KingdeeConnectionUpdateSchema(KingdeeConnectionCreateSchema):
    """金蝶连接配置更新模型(app_secret 为空表示不修改)。"""


class KingdeeConnectionOutSchema(KingdeeConnectionCreateSchema, BaseSchema, UserBySchema):
    """金蝶连接配置输出模型(密钥不返回明文)。"""

    model_config = ConfigDict(from_attributes=True)

    app_secret: None = Field(default=None, exclude=True, repr=False, description="应用密钥(不返回)")
    has_secret: bool = Field(default=False, description="是否已配置应用密钥")

    @field_validator("app_secret", mode="before")
    @classmethod
    def mask_secret(cls, value) -> None:
        return None


class KingdeeConnectionQueryParam(BaseQueryParam, UserByQueryParam):
    """金蝶连接查询参数。"""

    name: str | None = Field(None, description="连接名称", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态(0:启用 1:停用)", json_schema_extra={"q": "eq"})


class KingdeeBillQuerySchema(BaseModel):
    """金蝶单据查询参数。"""

    source_id: int = Field(..., ge=1, description="金蝶连接配置ID")
    form_id: str = Field(..., min_length=1, max_length=128, description="表单标识(如 BD_MATERIAL)")
    field_keys: str = Field(default="", max_length=2000, description="查询字段，逗号分隔；空表示默认字段")
    filter_string: str = Field(default="", max_length=4000, description="过滤条件")
    order_string: str = Field(default="", max_length=2000, description="排序条件")
    top_row_count: int = Field(default=0, ge=0, description="最多返回行数(0 不限)")
    start_row: int = Field(default=0, ge=0, description="起始行")
    limit: int = Field(default=200, ge=1, le=2000, description="本页行数")

    @field_validator("form_id")
    @classmethod
    def strip_form_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("表单标识不能为空")
        return value


class KingdeeBillQueryResultSchema(BaseModel):
    """金蝶单据查询结果。"""

    source_id: int = Field(..., description="金蝶连接配置ID")
    form_id: str = Field(..., description="表单标识")
    fields: list[str] = Field(default_factory=list, description="字段名列表")
    row_count: int = Field(default=0, description="本页行数")
    items: list[dict] = Field(default_factory=list, description="查询结果行")


class KingdeeViewSchema(BaseModel):
    """金蝶业务对象查看参数。"""

    source_id: int = Field(..., ge=1, description="金蝶连接配置ID")
    form_id: str = Field(..., min_length=1, max_length=128, description="业务对象表单Id")
    data: dict = Field(default_factory=dict, description="View 请求 JSON 数据")

    @field_validator("form_id")
    @classmethod
    def strip_form_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("业务对象表单Id不能为空")
        return value
