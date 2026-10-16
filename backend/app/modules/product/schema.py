"""产品线分析接口模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductLineQueryParam(BaseModel):
    """产品线分析查询参数。"""

    period_value: str | None = Field(default=None, max_length=16, description="期间(YYYY-MM)，缺省取最新期间")
    calc_version: int | None = Field(default=None, ge=1, description="计算版本，缺省取最新版本")
    product_line: str | None = Field(default=None, max_length=128, description="产品线大类（模糊）")
    sku: str | None = Field(default=None, max_length=128, description="SKU（模糊）")
    salesman: str | None = Field(default=None, max_length=64, description="业务员（模糊）")
    order_type: str | None = Field(default=None, max_length=32, description="订单类型（模糊，如 批量）")
    platform: str | None = Field(default=None, max_length=64, description="平台（模糊）")
    shop: str | None = Field(default=None, max_length=64, description="店铺（模糊）")
    aggregate_level: str = Field(
        default="detail",
        description="返回层级：detail=产品线×SKU 明细、line=产品线小计、all=全部（含合计行）",
    )
    keyword: str | None = Field(default=None, max_length=128, description="产品线/SKU 模糊搜索")


class ProductLineFieldOutSchema(BaseModel):
    """字段目录项。"""

    model_config = ConfigDict(from_attributes=True)

    field_code: str = Field(..., description="字段编码（PRD-xx）")
    field_name: str = Field(..., description="字段名称")
    data_type: str = Field(..., description="数据类型")
    group: str = Field(..., description="字段分组")
    sensitive: bool = Field(default=False, description="是否敏感（成本毛利类）")
    excel_code: str = Field(default="", description="Excel 底稿编码")
    source: str = Field(default="", description="底稿来源")
    note: str = Field(default="", description="口径说明")
    status: str = Field(default="", description="可出性状态")
    status_label: str = Field(default="", description="可出性中文")
    stored_in: str = Field(..., description="落库位置 core/extra")


class ProductLineBuildResultSchema(BaseModel):
    """构建结果。"""

    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    line_count: int = Field(..., description="产品线大类数")
    sku_count: int = Field(..., description="SKU 数")
    detail_count: int = Field(default=0, description="明细行数")
    order_count: int = Field(..., description="订单数")
    intake_untaxed_sum: float = Field(..., description="接单未税合计")
    net_shipment_sum: float = Field(..., description="对外出货净额合计")
    matched_rows: int = Field(default=0, description="命中型号字典的订单行数")
    unmatched_rows: int = Field(default=0, description="未命中型号字典的订单行数")
    order_source_version: int = Field(default=0, description="订单全链路来源版本")
    model_count: int = Field(default=0, description="型号字典行数")
    category_count: int = Field(default=0, description="系列字典节点数")
    warnings: list[str] | None = Field(default=None, description="口径缺项提示")


class ProductLineBuildRunOutSchema(BaseModel):
    """构建批次。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    status: str = Field(..., description="状态")
    line_count: int = Field(..., description="产品线大类数")
    sku_count: int = Field(..., description="SKU 数")
    order_count: int = Field(..., description="订单数")
    intake_untaxed_sum: float | None = Field(default=None, description="接单未税合计")
    net_shipment_sum: float | None = Field(default=None, description="对外出货净额合计")
    matched_rows: int = Field(default=0, description="命中型号字典行数")
    unmatched_rows: int = Field(default=0, description="未命中型号字典行数")
    warnings: list[str] | None = Field(default=None, description="口径缺项提示")
    error: str | None = Field(default=None, description="错误信息")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_time: datetime | None = Field(default=None, description="创建时间")


class ProductLineStatsSchema(BaseModel):
    """期间汇总（页面顶部指标卡）。"""

    line_count: int = Field(default=0, description="产品线大类数")
    sku_count: int = Field(default=0, description="SKU 数")
    order_count: int = Field(default=0, description="订单数")
    intake_untaxed_sum: float | None = Field(default=None, description="接单未税合计")
    ship_untaxed_sum: float | None = Field(default=None, description="货物出货未税合计")
    net_shipment_sum: float | None = Field(default=None, description="对外出货净额合计")
    settlement_income_sum: float | None = Field(default=None, description="营销结算收入10%合计")
    top_lines: list[dict[str, Any]] = Field(default_factory=list, description="产品线 TopN（按净额）")
