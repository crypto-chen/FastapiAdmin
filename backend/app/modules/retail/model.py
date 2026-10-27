"""零售数据推送模型。

外部系统（奇门/聚水潭）把零售订单按页推送到本系统，落三张表：

- ``retail_sync_batch``：每次推送的批次、幂等键、处理计数与原始请求体；
- ``retail_order``：订单头（以 ``source + shop_id + so_id`` 为业务唯一键）；
- ``retail_order_item``：订单明细（以 ``order_id + line_key`` 唯一）。

订单头保存 ``period_value``（按出库/支付/下单时间归月），便于按期间回放给
现有的 ``sales_outbound_amount`` 指标取数。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class RetailSyncBatchModel(ModelMixin):
    """一次零售数据推送的处理批次。"""

    __tablename__: str = "retail_sync_batch"
    __table_args__: tuple = (
        UniqueConstraint("app_id", "request_key", name="uq_retail_sync_batch_app_request"),
        Index("ix_retail_sync_batch_app_created", "app_id", "created_time"),
        {"comment": "零售数据推送批次"},
    )
    __data_scope_exempt__: bool = True

    app_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="调用方应用标识")
    client_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="开放应用ID")
    request_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="幂等键(请求ID或请求体哈希)")
    request_id: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="调用方请求ID")
    source: Mapped[str] = mapped_column(
        String(32), default="qimen", nullable=False, comment="数据来源(默认 qimen)"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="success", nullable=False, comment="状态(success/partial/failed)"
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="原始请求体 SHA256")
    received_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="收到的订单数")
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="新增订单数")
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="更新订单数")
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="内容未变化的订单数")
    stale_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="旧版本被跳过的订单数")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="处理失败的订单数")
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="落库明细行数")
    periods: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="涉及期间")
    page_index: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="推送页码")
    page_size: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="推送页大小")
    has_next: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="上游是否还有下一页")
    params: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="上游查询参数")
    errors: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="逐单错误")
    result: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="首次处理结果(幂等重放)")
    raw_payload: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始请求体(超限时省略)")


class RetailShopModel(ModelMixin):
    """零售店铺/平台主数据（聚水潭店铺查询同步）。"""

    __tablename__: str = "retail_shop"
    __table_args__: tuple = (
        UniqueConstraint("source", "shop_id", name="uq_retail_shop_source_shop"),
        Index("ix_retail_shop_site", "shop_site"),
        {"comment": "零售店铺/平台主数据"},
    )
    __data_scope_exempt__: bool = True

    source: Mapped[str] = mapped_column(
        String(32), default="jushuitan", nullable=False, index=True, comment="来源"
    )
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="店铺编号")
    shop_name: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="聚水潭店铺名称")
    shop_site: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="平台/站点"
    )
    platform_shop_name: Mapped[str | None] = mapped_column(
        String(128), default=None, nullable=True, comment="平台店铺名称"
    )
    co_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="公司编号")
    nick: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="授权账号")
    session_status: Mapped[int | None] = mapped_column(
        Integer, default=None, nullable=True, comment="授权状态(0未授权 1已过期 2已授权 3无需授权)"
    )
    session_expired: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="授权过期时间"
    )
    group_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="分组ID")
    group_name: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="分组名称")
    shop_url: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True, comment="店铺网址")
    short_name: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="店铺简称")
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True, comment="最近同步时间"
    )
    raw: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始店铺 JSON")


class RetailOrderModel(ModelMixin):
    """零售订单头（外部推送）。"""

    __tablename__: str = "retail_order"
    __table_args__: tuple = (
        UniqueConstraint("order_key", name="uq_retail_order_key"),
        Index("ix_retail_order_period_shop", "period_value", "shop_id"),
        Index("ix_retail_order_modified", "modified_time"),
        {"comment": "零售订单头（外部推送）"},
    )
    __data_scope_exempt__: bool = True

    order_key: Mapped[str] = mapped_column(
        String(160), nullable=False, comment="业务唯一键(source:shop_id:so_id/o_id)"
    )
    source: Mapped[str] = mapped_column(String(32), default="qimen", nullable=False, index=True, comment="来源")
    shop_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True, comment="店铺编码")
    so_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="线上单号")
    o_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="内部单号")
    co_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="公司编码")
    status: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, index=True, comment="订单状态")
    order_from: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="订单来源")
    shop_name: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="店铺名称")
    shop_site: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="店铺平台")
    buyer_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="买家ID")
    buyer_nick: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="买家昵称")
    order_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="下单时间")
    pay_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="支付时间")
    modified_time: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="上游修改时间")
    plan_delivery_date: Mapped[datetime | None] = mapped_column(
        DateTime, default=None, nullable=True, comment="计划发货时间"
    )
    period_value: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="归属期间(YYYY-MM)")
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="支付金额")
    pay_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="应付金额")
    buyer_paid_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="买家实付金额"
    )
    seller_income_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="卖家实收金额"
    )
    freight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="运费")
    free_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="优惠金额")
    receiver_state: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="收货省")
    receiver_city: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="收货市")
    receiver_district: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="收货区")
    receiver_town: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="收货街道")
    remark: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="订单备注")
    seller_flag: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="卖家标记")
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="明细行数")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="订单内容 SHA256")
    first_batch_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="首次入库批次")
    last_batch_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="最近入库批次")
    raw: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始订单 JSON")


class RetailOrderItemModel(ModelMixin):
    """零售订单明细（外部推送）。"""

    __tablename__: str = "retail_order_item"
    __table_args__: tuple = (
        UniqueConstraint("order_id", "line_key", name="uq_retail_order_item_line"),
        Index("ix_retail_order_item_sku", "sku_id"),
        {"comment": "零售订单明细（外部推送）"},
    )
    __data_scope_exempt__: bool = True

    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("retail_order.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="订单ID",
    )
    line_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="行唯一键(oi_id 或行哈希)")
    oi_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="明细行号")
    sku_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="SKU编码")
    i_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="商品编码")
    name: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True, comment="商品名称")
    properties_value: Mapped[str | None] = mapped_column(
        String(512), default=None, nullable=True, comment="规格属性"
    )
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="数量")
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="单价")
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="基础单价")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="明细金额")
    buyer_paid_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="买家实付"
    )
    seller_income_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="卖家实收"
    )
    item_pay_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="明细支付金额"
    )
    item_status: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="明细状态")
    refund_status: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="退款状态")
    is_gift: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否赠品")
    src_combine_sku_id: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="来源组合装SKU"
    )
    raw: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始明细 JSON")


class RetailAfterSaleModel(ModelMixin):
    """零售售后/退货退款单（聚水潭非淘系拉取 + 奇门淘系推送）。"""

    __tablename__: str = "retail_after_sale"
    __table_args__: tuple = (
        UniqueConstraint("as_key", name="uq_retail_after_sale_key"),
        Index("ix_retail_after_sale_period_shop", "period_value", "shop_id"),
        Index("ix_retail_after_sale_modified", "modified_time"),
        {"comment": "零售售后/退货退款单"},
    )
    __data_scope_exempt__: bool = True

    as_key: Mapped[str] = mapped_column(String(180), nullable=False, comment="唯一键(source:as_id/outer_as_id)")
    source: Mapped[str] = mapped_column(String(32), default="jushuitan", nullable=False, index=True, comment="来源")
    as_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="售后单号")
    outer_as_id: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="平台售后单号")
    o_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="订单内部单号")
    so_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="订单线上单号")
    shop_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True, comment="店铺编号")
    shop_name: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="店铺名称")
    shop_site: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="平台/站点")
    type: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="售后类型")
    status: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, index=True, comment="售后状态")
    shop_status: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="平台售后状态")
    good_status: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="货物状态")
    order_status: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="原订单状态")
    as_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="申请时间")
    registered_time: Mapped[datetime | None] = mapped_column(
        DateTime, default=None, nullable=True, comment="登记时间"
    )
    modified_time: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="修改时间")
    confirm_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="确认时间")
    period_value: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="归属期间(YYYY-MM)")
    refund: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="商品应退金额")
    payment: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="补偿金额")
    free_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="优惠/差额")
    freight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="卖家应退运费")
    actual_refund: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="实退金额(freight+refund-payment-free_amount)"
    )
    buyer_apply_refund: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="线上申请金额"
    )
    receive_refund: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="实际退给买家金额"
    )
    seller_real_refund: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="商家实退+平台补贴"
    )
    buyer_paid_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="营收小计-买家实付"
    )
    seller_income_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="营收小计-卖家实收"
    )
    platform_promotion: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="平台补贴"
    )
    platform_free_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="平台补贴(营收小计)"
    )
    government_free_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="政府补贴"
    )
    warehouse: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="退回仓库")
    wms_co_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="收货仓编码")
    l_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="退回物流单号")
    logistics_company: Mapped[str | None] = mapped_column(
        String(128), default=None, nullable=True, comment="退回物流公司"
    )
    remark: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")
    result: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="处理结果")
    node: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="线下备注")
    currency: Mapped[str | None] = mapped_column(String(16), default=None, nullable=True, comment="币种")
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="明细行数")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="内容 SHA256")
    last_batch_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="最近同步批次")
    raw: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始售后 JSON")


class RetailAfterSaleItemModel(ModelMixin):
    """零售售后/退货退款明细。"""

    __tablename__: str = "retail_after_sale_item"
    __table_args__: tuple = (
        UniqueConstraint("after_sale_id", "line_key", name="uq_retail_after_sale_item_line"),
        Index("ix_retail_after_sale_item_sku", "sku_id"),
        {"comment": "零售售后/退货退款明细"},
    )
    __data_scope_exempt__: bool = True

    after_sale_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("retail_after_sale.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="售后单ID",
    )
    line_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="行唯一键(asi_id 或行哈希)")
    asi_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="售后子单号")
    sku_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="SKU编码")
    i_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="款式编码")
    name: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True, comment="商品名称")
    properties_value: Mapped[str | None] = mapped_column(
        String(512), default=None, nullable=True, comment="规格属性"
    )
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="申请数量")
    r_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="实收退货数量")
    defective_qty: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="次品数量"
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="单价")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="申请金额")
    shop_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="线上明细金额"
    )
    buyer_paid_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="买家实付"
    )
    seller_income_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), default=None, nullable=True, comment="卖家实收"
    )
    type: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="明细类型")
    is_gift: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否赠品")
    sku_type: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="商品类型")
    combine_sku_id: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="组合商品编码"
    )
    outer_oi_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="子订单号")
    raw_so_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="原始线上订单号")
    receive_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="入仓时间")
    raw: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始明细 JSON")
