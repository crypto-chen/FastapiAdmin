"""订单全链路接口模型。"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderQueryParam(BaseModel):
    """订单全链路查询参数。"""

    period_value: str | None = Field(default=None, max_length=16, description="期间(YYYY-MM)，缺省取最新期间")
    calc_version: int | None = Field(default=None, ge=1, description="计算版本，缺省取最新版本")
    order_number: str | None = Field(default=None, max_length=64, description="订单号（模糊）")
    trade_type: str | None = Field(default=None, max_length=16, description="贸易类型 domestic/export")
    order_type: str | None = Field(default=None, max_length=16, description="订单类型 1/2/3")
    customer_name: str | None = Field(default=None, max_length=128, description="客户（模糊）")
    salesman_code: str | None = Field(default=None, max_length=64, description="业务员编码")
    data_quality_flag: str | None = Field(default=None, max_length=64, description="数据质量标记")
    keyword: str | None = Field(default=None, max_length=64, description="订单号/客户 模糊搜索")


class OrderFieldOutSchema(BaseModel):
    """字段目录项。"""

    model_config = ConfigDict(from_attributes=True)

    field_code: str = Field(..., description="字段编码")
    field_name: str = Field(..., description="字段名称")
    data_type: str = Field(..., description="数据类型")
    group: str = Field(..., description="字段分组")
    sensitive: bool = Field(default=False, description="是否敏感（成本/毛利类）")
    stored_in: str = Field(..., description="落库位置 core/extra")


class OrderRowOutSchema(BaseModel):
    """订单宽表一行（核心列 + extra 展开）。"""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: int = Field(..., description="主键")
    order_number: str = Field(..., description="订单号")
    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    trade_type: str | None = Field(default=None, description="贸易类型")
    order_type: str | None = Field(default=None, description="订单类型")
    customer_id: int | None = Field(default=None, description="客户ID")
    salesman_code: str | None = Field(default=None, description="业务员编码")
    order_date: date | None = Field(default=None, description="接单日期")
    push_date: datetime | None = Field(default=None, description="下推日期")
    finish_date: datetime | None = Field(default=None, description="齐套入库日期")
    ship_date: datetime | None = Field(default=None, description="销售出库日期")
    qty: float | None = Field(default=None, description="数量")
    intake_untaxed: float | None = Field(default=None, description="接单未税")
    ship_untaxed: float | None = Field(default=None, description="出货未税")
    net_shipment: float | None = Field(default=None, description="净出货")
    data_quality_flag: str | None = Field(default=None, description="数据质量标记")


class OrderBuildResultSchema(BaseModel):
    """构建结果。"""

    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    order_count: int = Field(..., description="订单数")
    mo_linked_count: int = Field(..., description="关联到生产订单的订单数")
    cost_missing_count: int = Field(..., description="成本缺失订单数")
    source_batches: dict[str, Any] | None = Field(default=None, description="来源批次清单")


class OrderBuildRunOutSchema(BaseModel):
    """构建批次。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    period_value: str = Field(..., description="期间")
    calc_version: int = Field(..., description="计算版本")
    status: str = Field(..., description="状态")
    order_count: int = Field(..., description="订单数")
    mo_linked_count: int = Field(..., description="关联生产订单数")
    cost_missing_count: int = Field(..., description="成本缺失数")
    error: str | None = Field(default=None, description="错误信息")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    created_time: datetime | None = Field(default=None, description="创建时间")
