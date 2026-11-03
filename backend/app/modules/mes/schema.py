"""MES 订单查询参数与返回结构。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class MesOrderQueryParam(BaseModel):
    """MES 订单查询条件（全部可选，多个条件按 AND 组合）。"""

    crm_order_no: str | None = Field(default=None, max_length=64, description="CRM 订单号（模糊）")
    customer_name: str | None = Field(default=None, max_length=255, description="客户名称（模糊）")
    engineer_name: str | None = Field(default=None, max_length=128, description="负责工程姓名（模糊）")
    product_series: str | None = Field(default=None, max_length=128, description="产品系列（模糊）")
    product_model: str | None = Field(default=None, max_length=128, description="产品型号（模糊）")
    product_size: str | None = Field(default=None, max_length=128, description="产品尺寸（模糊）")
    trade_type: Literal["domestic", "export"] | None = Field(default=None, description="贸易类型：domestic=内贸，export=外贸；不传=全部")


class MesOrderItemSchema(BaseModel):
    """MES 读取的一条 CRM 内外贸订单。"""

    crm_order_no: str = Field(..., description="CRM 订单号")
    customer_name: str | None = Field(default=None, description="客户名称")
    engineer_name: str | None = Field(default=None, description="负责工程")
    product_series: str | None = Field(default=None, description="产品系列")
    product_model: str | None = Field(default=None, description="产品型号")
    product_size: str | None = Field(default=None, description="产品尺寸")
    quantity: float | None = Field(default=None, description="数量")
    trade_type: str | None = Field(default=None, description="贸易类型 domestic/export")
    order_date: date | None = Field(default=None, description="接单日期")
