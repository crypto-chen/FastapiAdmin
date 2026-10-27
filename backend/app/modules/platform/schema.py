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
