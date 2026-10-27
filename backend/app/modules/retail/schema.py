"""零售数据推送请求/响应模型。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RetailSyncPayload(BaseModel):
    """兼容奇门/聚水潭的多种返回包裹形式。

    可直接提交上游原始响应（``{"orders": [...]}``），也可提交
    ``{"data": {"orders": [...]}}``、``{"data": [...]}`` 或裸订单数组。
    """

    model_config = ConfigDict(extra="allow")

    request_id: str | None = Field(default=None, max_length=128, description="幂等请求ID，建议每次推送唯一")
    source: str | None = Field(default=None, max_length=32, description="数据来源标识，缺省 qimen")
    orders: list[dict[str, Any]] | dict[str, Any] | str | None = Field(
        default=None, description="订单数组；低代码平台也可传 JSON 字符串"
    )
    datas: list[dict[str, Any]] | dict[str, Any] | str | None = Field(
        default=None, description="聚水潭 datas 数组；也兼容 JSON 字符串"
    )
    data: dict[str, Any] | list[dict[str, Any]] | str | None = Field(
        default=None, description="上游 data 包裹（对象、订单数组或 JSON 字符串）"
    )
    params: dict[str, Any] | None = Field(default=None, description="上游查询参数")
    page_index: int | None = Field(default=None, ge=1, description="上游页码")
    page_size: int | None = Field(default=None, ge=1, description="上游页大小")
    has_next: bool | None = Field(default=None, description="上游是否还有下一页")
    data_count: int | None = Field(default=None, ge=0, description="上游声明的订单数")


class RetailSyncErrorSchema(BaseModel):
    """单个订单的处理错误。"""

    index: int = Field(..., description="订单在本次请求中的下标")
    order_id: str | None = Field(default=None, description="订单号（能解析时返回）")
    reason: str = Field(..., description="失败原因")


class RetailSyncResultSchema(BaseModel):
    """推送处理结果。"""

    batch_id: str = Field(..., description="本系统批次ID")
    request_id: str | None = Field(default=None, description="调用方请求ID")
    duplicate: bool = Field(default=False, description="是否命中幂等重放")
    received: int = Field(default=0, description="本次收到的订单数")
    created: int = Field(default=0, description="新增订单数")
    updated: int = Field(default=0, description="更新订单数")
    unchanged: int = Field(default=0, description="内容未变化的订单数")
    stale: int = Field(default=0, description="上游版本较旧而跳过的订单数")
    failed: int = Field(default=0, description="处理失败的订单数")
    item_count: int = Field(default=0, description="落库明细行数")
    periods: list[str] = Field(default_factory=list, description="涉及的期间 YYYY-MM")
    has_next: bool = Field(default=False, description="上游是否还有下一页")
    errors: list[RetailSyncErrorSchema] = Field(default_factory=list, description="逐单错误")
    metric_sync: list[dict[str, Any]] = Field(
        default_factory=list, description="已回放到同步批次/指标取数层的结果"
    )


class RetailOrderQueryParam(BaseModel):
    """管理端零售订单查询参数。"""

    period_value: str | None = Field(default=None, max_length=16, description="期间(YYYY-MM)")
    shop_id: int | None = Field(default=None, ge=0, description="店铺编码")
    shop_name: str | None = Field(default=None, max_length=128, description="店铺名称（模糊）")
    so_id: str | None = Field(default=None, max_length=64, description="线上/内部单号（模糊）")
    status: str | None = Field(default=None, max_length=32, description="订单状态")
    source: str | None = Field(default=None, max_length=32, description="来源")
    keyword: str | None = Field(default=None, max_length=128, description="单号/店铺/买家/备注模糊搜索")


class RetailBatchQueryParam(BaseModel):
    """管理端推送批次查询参数。"""

    biz_type: str | None = Field(default=None, max_length=16, description="业务类型: order/after_sale")
    request_id: str | None = Field(default=None, max_length=128, description="请求ID（模糊）")
    app_id: str | None = Field(default=None, max_length=64, description="调用方标识")
    source: str | None = Field(default=None, max_length=32, description="来源")
    status: str | None = Field(default=None, max_length=16, description="批次状态")


class RetailAfterSaleErrorSchema(BaseModel):
    """售后单处理错误。"""

    index: int = Field(..., description="售后单在本次请求中的下标")
    as_id: str | None = Field(default=None, description="售后单号")
    reason: str = Field(..., description="失败原因")


class RetailAfterSaleResultSchema(BaseModel):
    """售后同步结果。"""

    batch_id: str = Field(..., description="本系统批次ID")
    request_id: str | None = Field(default=None, description="调用方请求ID")
    duplicate: bool = Field(default=False, description="是否命中幂等重放")
    received: int = Field(default=0, description="收到的售后单数")
    created: int = Field(default=0, description="新增售后单数")
    updated: int = Field(default=0, description="更新售后单数")
    unchanged: int = Field(default=0, description="内容未变化数")
    stale: int = Field(default=0, description="旧版本跳过数")
    failed: int = Field(default=0, description="失败数")
    item_count: int = Field(default=0, description="落库明细行数")
    periods: list[str] = Field(default_factory=list, description="涉及期间")
    errors: list[RetailAfterSaleErrorSchema] = Field(default_factory=list, description="逐单错误")


class RetailAfterSaleQueryParam(BaseModel):
    """管理端售后查询参数。"""

    period_value: str | None = Field(default=None, max_length=16, description="期间(YYYY-MM)")
    shop_id: int | None = Field(default=None, ge=0, description="店铺编号")
    shop_name: str | None = Field(default=None, max_length=128, description="店铺名称（模糊）")
    as_id: str | None = Field(default=None, max_length=128, description="售后单号（模糊）")
    so_id: str | None = Field(default=None, max_length=64, description="订单号（模糊）")
    status: str | None = Field(default=None, max_length=32, description="售后状态")
    type: str | None = Field(default=None, max_length=32, description="售后类型")
    keyword: str | None = Field(default=None, max_length=128, description="售后单/订单/店铺/买家模糊搜索")
