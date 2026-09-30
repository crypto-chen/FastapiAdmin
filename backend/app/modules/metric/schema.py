from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema


class MetricDefCreateSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, description="指标编码")
    name: str = Field(..., min_length=1, max_length=255, description="指标名称")
    excel_code: str | None = Field(default=None, max_length=64, description="Excel 科目编码（财务口径对照编码）")
    period_type: str = Field(default="month", min_length=1, max_length=16, description="期间类型")
    sensitivity: int = Field(default=0, ge=0, le=2, description="敏感级别(0普通 1敏感 2机密)")
    formula: str | None = Field(default=None, max_length=4000, description="计算公式")
    dimensions: dict | None = Field(default=None, description="维度配置")
    measures: dict | None = Field(default=None, description="度量配置")
    source_entity_id: int | None = Field(default=None, ge=1, description="来源标准实体ID")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("code", "name", "period_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("指标编码、名称、期间类型不能为空")
        return value


class MetricDefUpdateSchema(MetricDefCreateSchema):
    pass


class MetricDefOutSchema(MetricDefCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    version: int = Field(default=1, description="版本号")
    source_entity_code: str | None = Field(default=None, description="标准实体编码")
    source_entity_name: str | None = Field(default=None, description="标准实体名称")


class MetricDefQueryParam(BaseQueryParam, UserByQueryParam):
    code: str | None = Field(None, description="指标编码", json_schema_extra={"q": "like"})
    name: str | None = Field(None, description="指标名称", json_schema_extra={"q": "like"})
    excel_code: str | None = Field(None, description="Excel 科目编码", json_schema_extra={"q": "like"})
    period_type: str | None = Field(None, description="期间类型", json_schema_extra={"q": "eq"})
    sensitivity: int | None = Field(None, ge=0, le=2, description="敏感级别", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class MetricValueQueryParam(BaseQueryParam):
    """指标结果查询参数；不传 ``calc_version`` 时默认只返回最新一次计算的版本。"""

    metric_id: int | None = Field(None, ge=1, description="指标定义ID", json_schema_extra={"q": "eq"})
    period_type: str | None = Field(None, description="期间类型", json_schema_extra={"q": "eq"})
    period_value: str | None = Field(None, description="期间值", json_schema_extra={"q": "eq"})
    org_id: int | None = Field(None, ge=1, description="组织ID", json_schema_extra={"q": "eq"})
    dept_id: int | None = Field(None, ge=1, description="核算维度（部门/客户）ID", json_schema_extra={"q": "eq"})
    calc_version: int | None = Field(None, ge=1, description="计算版本", json_schema_extra={"q": "eq"})
    level: Literal["org", "dept", "all"] = Field(
        default="org",
        description="展示层级：org=仅组织合计 dept=仅核算维度明细 all=全部（由服务层翻译，不参与等值过滤）",
    )


class MetricValueOutSchema(BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    metric_id: int = Field(..., description="指标定义ID")
    run_id: int | None = Field(default=None, description="计算批次ID")
    period_type: str = Field(..., description="期间类型")
    period_value: str = Field(..., description="期间值")
    org_id: int | None = Field(default=None, description="组织ID")
    dept_id: int | None = Field(default=None, description="部门ID")
    dept_code: str | None = Field(default=None, description="核算维度编码(原始)")
    person_id: int | None = Field(default=None, description="人员ID")
    value: float = Field(default=0, description="指标值")
    version: int = Field(default=1, description="指标版本")
    calc_version: int = Field(default=1, description="计算版本")
    batch_id: str | None = Field(default=None, description="计算批次ID")
    filter_signature: str | None = Field(default=None, description="取数条件签名")
    calc_time: datetime | None = Field(default=None, description="计算时间")
    org_code: str | None = Field(default=None, description="组织编码")
    org_name: str | None = Field(default=None, description="组织名称")
    dept_name: str | None = Field(default=None, description="核算维度名称")


class MetricCalcRequestSchema(BaseModel):
    period_value: str | None = Field(default=None, max_length=32, description="期间值，缺省取当前期间")
    org_codes: list[str] | None = Field(default=None, description="限定组织编码，缺省为全部组织")


class MetricCalcResultSchema(BaseModel):
    metric_id: int = Field(..., description="指标定义ID")
    metric_code: str = Field(..., description="指标编码")
    period_type: str = Field(..., description="期间类型")
    period_value: str = Field(..., description="期间值")
    calc_version: int = Field(..., description="计算版本")
    batch_id: str = Field(..., description="计算批次ID")
    partial: bool = Field(default=False, description="是否按组织范围部分重算")
    backfilled_orgs: list[str] = Field(default_factory=list, description="该期间缺批次、已按期间回补取数的组织")
    backfilled_components: list[str] = Field(
        default_factory=list, description="汇总指标：该期间缺结果、已临时补算的组成指标"
    )
    org_count: int = Field(default=0, description="参与计算的组织数")
    skipped_orgs: list[str] = Field(default_factory=list, description="无同步数据被跳过的组织")
    skipped: bool = Field(default=False, description="是否跳过计算（如指标未配置取数规则）")
    reason: str | None = Field(default=None, description="跳过计算的原因")
    total: float = Field(default=0, description="全部组织合计")
    orgs: dict = Field(default_factory=dict, description="各组织计算结果")
