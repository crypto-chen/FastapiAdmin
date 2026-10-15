"""客户分析接口模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CustomerQueryParam(BaseModel):
    """客户分析查询参数。"""

    period_value: str | None = Field(default=None, max_length=16, description="期间(YYYY-MM)，缺省取最新期间")
    calc_version: int | None = Field(default=None, ge=1, description="计算版本，缺省取最新版本")
    customer_code: str | None = Field(default=None, max_length=64, description="客户编码（模糊）")
    customer_name: str | None = Field(default=None, max_length=128, description="客户名称（模糊）")
    salesman_code: str | None = Field(default=None, max_length=64, description="业务员编码")
    order_type: str | None = Field(default=None, max_length=64, description="订单类型（模糊，如 批量）")
    product_line: str | None = Field(default=None, max_length=64, description="产品线大类（模糊）")
    trade_type: str | None = Field(default=None, max_length=64, description="贸易类型（内贸/外贸）")
    include_aggregate: bool = Field(default=True, description="是否返回合计行")
    keyword: str | None = Field(default=None, max_length=64, description="客户编码/名称 模糊搜索")


class CustomerFieldOutSchema(BaseModel):
    """字段目录项。"""

    model_config = ConfigDict(from_attributes=True)

    field_code: str = Field(..., description="字段编码（CUS-xx）")
    field_name: str = Field(..., description="字段名称")
    data_type: str = Field(..., description="数据类型")
    group: str = Field(..., description="字段分组")
    sensitive: bool = Field(default=False, description="是否敏感（成本毛利类）")
    excel_code: str = Field(default="", description="Excel 底稿编码")
    source: str = Field(default="", description="底稿来源")
    note: str = Field(default="", description="口径说明")
    stored_in: str = Field(..., description="落库位置 core/extra")


class CustomerBuildResultSchema(BaseModel):
    """构建结果。"""

    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    customer_count: int = Field(..., description="客户数")
    order_count: int = Field(..., description="订单数")
    intake_untaxed_sum: float = Field(..., description="接单未税合计")
    net_shipment_sum: float = Field(..., description="对外出货净额合计")
    master_customer_count: int = Field(..., description="客户主档总数(时点)")
    order_source_version: int = Field(default=0, description="订单全链路来源版本")
    company_base: dict[str, Any] | None = Field(default=None, description="公司口径分摊基数")
    warnings: list[str] | None = Field(default=None, description="口径缺项提示")


class CustomerBuildRunOutSchema(BaseModel):
    """构建批次。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    status: str = Field(..., description="状态")
    customer_count: int = Field(..., description="客户数")
    order_count: int = Field(..., description="订单数")
    intake_untaxed_sum: float | None = Field(default=None, description="接单未税合计")
    net_shipment_sum: float | None = Field(default=None, description="对外出货净额合计")
    master_customer_count: int = Field(default=0, description="客户主档总数(时点)")
    warnings: list[str] | None = Field(default=None, description="口径缺项提示")
    error: str | None = Field(default=None, description="错误信息")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_time: datetime | None = Field(default=None, description="创建时间")
