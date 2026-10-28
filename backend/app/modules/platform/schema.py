"""平台分析查询参数。"""

from pydantic import BaseModel, Field


class PlatformAnalysisQueryParam(BaseModel):
    """平台分析列表查询参数。"""

    period_value: str | None = Field(default=None, max_length=16, description="期间 YYYY-MM")
    platform: str | None = Field(default=None, max_length=32, description="平台（归一后）")
    shop_id: int | None = Field(default=None, ge=0, description="店铺编号")
    keyword: str | None = Field(default=None, max_length=128, description="平台/店铺（模糊）")
    aggregate_level: str = Field(
        default="detail", pattern="^(detail|platform|all)$", description="detail=店铺明细 / platform=平台小计 / all=全部"
    )
    page_no: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=50, ge=1, le=500, description="每页数量")


class PlatformMetricUpsertParam(BaseModel):
    """平台指标配置（新增/修改）。"""

    code: str = Field(..., min_length=2, max_length=32, description="指标编码，如 PLT-39")
    name: str = Field(..., min_length=1, max_length=128, description="指标名称")
    group: str = Field(default="金额", max_length=32, description="分组：维度/数量/金额/比率")
    data_type: str = Field(default="number", pattern="^(number|percent|string)$", description="数据类型")
    unit: str | None = Field(default=None, max_length=16, description="单位")
    sensitive: bool = Field(default=False, description="是否敏感字段")
    expression: str = Field(
        default="",
        max_length=1000,
        description="取值表达式；现用可出(ready)必填，待确认/待做可留空",
    )
    readiness: str = Field(
        default="ready",
        pattern="^(ready|pending|todo|missing)$",
        description="可出性：ready 现用可出 / pending 待确认 / todo 待做 / missing 缺数据源",
    )
    note: str | None = Field(default=None, max_length=1000, description="口径说明")
    sort: int = Field(default=100, ge=0, le=9999, description="列顺序")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
