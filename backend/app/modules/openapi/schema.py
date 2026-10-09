from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema


class OpenClientCreateSchema(BaseModel):
    """新建接入应用。``app_secret`` 由服务端生成，不接受外部传入。"""

    app_id: str = Field(..., min_length=2, max_length=64, description="应用标识（对外暴露的唯一 ID）")
    name: str = Field(..., min_length=1, max_length=128, description="应用名称")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    ip_whitelist: str | None = Field(default=None, max_length=500, description="IP 白名单，逗号分隔，空=不限制")
    token_ttl_seconds: int = Field(default=7200, ge=300, le=604800, description="令牌有效期(秒)")
    rate_limit: int = Field(default=600, ge=1, le=100000, description="每分钟最大请求数")
    allow_dept_detail: bool = Field(default=False, description="是否允许查询核算维度明细")
    allow_person_detail: bool = Field(default=False, description="是否允许查询业务员明细")
    allow_run_calc: bool = Field(default=False, description="是否允许触发指标重算")
    org_scope: list[str] | None = Field(default=None, description="允许的组织编码，空=全部启用组织")
    expire_time: datetime | None = Field(default=None, description="凭证到期时间，空=长期有效")
    contact: str | None = Field(default=None, max_length=128, description="联系人")
    description: str | None = Field(default=None, max_length=500, description="用途备注")

    @field_validator("app_id", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("应用标识与应用名称不能为空")
        return value


class OpenClientUpdateSchema(BaseModel):
    """修改接入应用；``app_id`` 不可变，密钥走独立的重置接口。"""

    name: str | None = Field(default=None, min_length=1, max_length=128, description="应用名称")
    status: int | None = Field(default=None, ge=0, le=1, description="状态(0:启用 1:停用)")
    ip_whitelist: str | None = Field(default=None, max_length=500, description="IP 白名单，逗号分隔，空=不限制")
    token_ttl_seconds: int | None = Field(default=None, ge=300, le=604800, description="令牌有效期(秒)")
    rate_limit: int | None = Field(default=None, ge=1, le=100000, description="每分钟最大请求数")
    allow_dept_detail: bool | None = Field(default=None, description="是否允许查询核算维度明细")
    allow_person_detail: bool | None = Field(default=None, description="是否允许查询业务员明细")
    allow_run_calc: bool | None = Field(default=None, description="是否允许触发指标重算")
    org_scope: list[str] | None = Field(default=None, description="允许的组织编码，空=全部启用组织")
    expire_time: datetime | None = Field(default=None, description="凭证到期时间，空=长期有效")
    contact: str | None = Field(default=None, max_length=128, description="联系人")
    description: str | None = Field(default=None, max_length=500, description="用途备注")


class OpenClientOutSchema(BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    app_id: str = Field(..., description="应用标识")
    name: str = Field(..., description="应用名称")
    status: int = Field(default=0, description="状态(0:启用 1:停用)")
    ip_whitelist: str | None = Field(default=None, description="IP 白名单")
    token_ttl_seconds: int = Field(default=7200, description="令牌有效期(秒)")
    rate_limit: int = Field(default=600, description="每分钟最大请求数")
    allow_dept_detail: bool = Field(default=False, description="是否允许查询核算维度明细")
    allow_person_detail: bool = Field(default=False, description="是否允许查询业务员明细")
    allow_run_calc: bool = Field(default=False, description="是否允许触发指标重算")
    org_scope: list[str] | None = Field(default=None, description="允许的组织编码")
    expire_time: datetime | None = Field(default=None, description="凭证到期时间")
    contact: str | None = Field(default=None, description="联系人")
    description: str | None = Field(default=None, description="用途备注")


class OpenClientCreateResultSchema(OpenClientOutSchema):
    """新建 / 重置密钥的结果：``app_secret`` 仅此一次返回明文。"""

    app_secret: str = Field(..., description="应用密钥（仅本次返回，请立即保存）")


class OpenClientQueryParam(BaseQueryParam, UserByQueryParam):
    app_id: str | None = Field(None, description="应用标识", json_schema_extra={"q": "like"})
    name: str | None = Field(None, description="应用名称", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class OpenApiLogOutSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    client_id: int | None = Field(default=None, description="应用ID")
    app_id: str | None = Field(default=None, description="应用标识")
    path: str = Field(..., description="请求路径")
    method: str = Field(..., description="请求方法")
    params: dict | None = Field(default=None, description="请求参数")
    response_code: int = Field(default=0, description="业务状态码")
    http_status: int = Field(default=200, description="HTTP 状态码")
    cost_ms: int = Field(default=0, description="耗时(毫秒)")
    client_ip: str | None = Field(default=None, description="调用方 IP")
    description: str | None = Field(default=None, description="接口说明")


class OpenApiLogQueryParam(BaseQueryParam):
    app_id: str | None = Field(None, description="应用标识", json_schema_extra={"q": "like"})
    path: str | None = Field(None, description="请求路径", json_schema_extra={"q": "like"})
    method: str | None = Field(None, description="请求方法", json_schema_extra={"q": "eq"})
    http_status: int | None = Field(None, ge=100, le=599, description="HTTP 状态码", json_schema_extra={"q": "eq"})
    client_ip: str | None = Field(None, description="调用方 IP", json_schema_extra={"q": "like"})


# ── 对外开放接口模型 ──────────────────────────────────────────────


class OpenTokenRequestSchema(BaseModel):
    app_id: str = Field(..., min_length=1, max_length=64, description="应用标识")
    app_secret: str = Field(..., min_length=1, max_length=128, description="应用密钥")
    grant_type: Literal["client_credentials"] = Field(default="client_credentials", description="授权类型")


class OpenTokenOutSchema(BaseModel):
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")
    expires_in: int = Field(..., gt=0, description="有效期(秒)")


class OpenMetricOutSchema(BaseModel):
    code: str = Field(..., description="指标编码")
    name: str = Field(..., description="指标名称")
    excel_code: str | None = Field(default=None, description="Excel 科目编码（财务口径对照编码）")
    period_type: str = Field(..., description="期间类型(day/week/month/year)")
    unit: str = Field(default="元", description="单位")
    dimensions: list[str] = Field(default_factory=list, description="核算维度")
    description: str | None = Field(default=None, description="口径说明")


class OpenMetricQuerySchema(BaseModel):
    """批量取数请求；期间区间上下界均包含，不传则取当前期间。"""

    metrics: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="指标编码或 Excel 科目编码（如 marketing_office_expense / EXP-01-a），上限 20 个",
    )
    period_type: Literal["day", "week", "month", "year"] = Field(default="month", description="期间类型")
    period_start: str | None = Field(default=None, max_length=32, description="起始期间(含)")
    period_end: str | None = Field(default=None, max_length=32, description="结束期间(含)")
    org_codes: list[str] | None = Field(default=None, max_length=200, description="组织编码，空=授权范围内全部")
    person_codes: list[str] | None = Field(
        default=None, max_length=200, description="业务员编码（如 CRM 用户名），空=全部业务员；level=person 时生效"
    )
    person_ids: list[int] | None = Field(
        default=None, max_length=200, description="业务员主ID（内部标准人员ID），空=全部；level=person 时生效"
    )
    level: Literal["org", "dept", "person", "all"] = Field(
        default="org", description="展示层级：org=组织合计 / dept=核算维度明细 / person=业务员明细 / all=全部"
    )
    format: Literal["long", "wide"] = Field(default="long", description="返回结构：long=长表 / wide=宽表")
    total_only: bool = Field(
        default=False, description="只返回合计：按「指标 × 期间」汇总，items 为空、结果在 totals 中"
    )
    include_meta: bool = Field(default=True, description="是否返回指标口径信息")


class OpenMetricValueItemSchema(BaseModel):
    metric_code: str = Field(..., description="指标编码")
    metric_name: str | None = Field(default=None, description="指标名称")
    excel_code: str | None = Field(default=None, description="Excel 科目编码（财务口径对照编码）")
    period_value: str = Field(..., description="期间值")
    org_code: str | None = Field(default=None, description="组织编码")
    org_name: str | None = Field(default=None, description="组织名称")
    dept_code: str | None = Field(default=None, description="核算维度编码")
    dept_name: str | None = Field(default=None, description="核算维度名称")
    person_code: str | None = Field(default=None, description="业务员编码（level=person 时返回）")
    person_name: str | None = Field(default=None, description="业务员姓名（level=person 时返回）")
    person_id: int | None = Field(default=None, description="业务员主ID（内部标准人员ID，level=person 时返回）")
    value: float = Field(default=0, description="指标值")
    calc_version: int = Field(default=1, description="计算版本")
    calc_time: datetime | None = Field(default=None, description="计算时间")
    batch_id: str | None = Field(default=None, description="计算批次ID")


class OpenMetricErrorSchema(BaseModel):
    metric_code: str = Field(..., description="指标编码")
    reason: str = Field(..., description="不可读原因")


class OpenOrgOutSchema(BaseModel):
    org_code: str = Field(..., description="组织编码")
    org_name: str = Field(..., description="组织名称")
    parent_code: str | None = Field(default=None, description="上级组织编码")
    level: int = Field(default=1, description="层级，从 1 开始")


class OpenMetricRunResultSchema(BaseModel):
    metric_code: str = Field(..., description="指标编码")
    period_type: str = Field(..., description="期间类型")
    period_value: str = Field(..., description="期间值")
    calc_version: int = Field(default=1, description="计算版本")
    total: float = Field(default=0, description="全部组织合计")
    org_count: int = Field(default=0, description="参与计算的组织数")
