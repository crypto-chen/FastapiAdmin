from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema


class JushuitanConnectionCreateSchema(BaseModel):
    """聚水潭连接配置创建模型。"""

    name: str = Field(..., min_length=1, max_length=64, description="连接名称")
    base_url: str = Field(
        default="https://openapi.jushuitan.com", max_length=255, description="接口地址(正式/测试环境)"
    )
    app_key: str = Field(..., min_length=1, max_length=255, description="开发者应用app_key")
    app_secret: str | None = Field(default=None, max_length=512, description="应用密钥app_secret")
    access_token: str | None = Field(default=None, max_length=512, description="商家授权access_token")
    shop_id: int | None = Field(default=None, ge=0, description="默认店铺编码(0=线下店铺)")
    is_offline_shop: int = Field(default=0, ge=0, le=1, description="是否只看线下店铺单据(0:否 1:是)")
    timeout: int = Field(default=30, ge=1, le=300, description="读取超时(秒)")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("name", "app_key")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("必填项不能为空")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = (value or "").strip().rstrip("/")
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError("接口地址必须以 http:// 或 https:// 开头")
        return value or "https://openapi.jushuitan.com"


class JushuitanConnectionUpdateSchema(JushuitanConnectionCreateSchema):
    """聚水潭连接配置更新模型（app_secret/access_token 为空表示不修改）。"""


class JushuitanConnectionOutSchema(JushuitanConnectionCreateSchema, BaseSchema, UserBySchema):
    """聚水潭连接配置输出模型（密钥不返回明文）。"""

    model_config = ConfigDict(from_attributes=True)

    app_secret: None = Field(default=None, exclude=True, repr=False, description="应用密钥(不返回)")
    access_token: None = Field(default=None, exclude=True, repr=False, description="授权令牌(不返回)")
    has_secret: bool = Field(default=False, description="是否已配置应用密钥")
    has_token: bool = Field(default=False, description="是否已配置access_token")

    @field_validator("app_secret", "access_token", mode="before")
    @classmethod
    def mask_secret(cls, value) -> None:
        return None


class JushuitanConnectionQueryParam(BaseQueryParam, UserByQueryParam):
    """聚水潭连接查询参数。"""

    name: str | None = Field(None, description="连接名称", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态(0:启用 1:停用)", json_schema_extra={"q": "eq"})


class JushuitanSalesOutboundQuerySchema(BaseModel):
    """销售出库查询参数（docId=34）。"""

    source_id: int = Field(..., ge=1, description="聚水潭连接配置ID")
    period_value: str | None = Field(
        default=None, max_length=32, description="月度期间(YYYY-MM)，与 begin/end 二选一"
    )
    begin: str | None = Field(default=None, max_length=32, description="起始时间 yyyy-MM-dd HH:mm:ss")
    end: str | None = Field(default=None, max_length=32, description="结束时间 yyyy-MM-dd HH:mm:ss")
    shop_id: int | None = Field(default=None, ge=0, description="店铺编码；不传取连接默认店铺")
    is_offline_shop: bool | None = Field(default=None, description="是否线下店铺单据")
    status: str | None = Field(default="Confirmed", description="单据状态；Confirmed=已出库，传空表示不过滤")
    date_type: int = Field(default=2, ge=0, le=2, description="时间类型 0=修改时间 2=出库时间")
    wms_co_id: int | None = Field(default=None, description="出库仓编号")
    page_size: int = Field(default=50, ge=1, le=50, description="每页条数，最大 50")
    max_rows: int = Field(default=20000, ge=1, le=200000, description="最多拉取的行数，防止异常情况下无限翻页")
    include_rows: bool = Field(default=False, description="是否在返回中携带明细行")

    @field_validator("period_value", "begin", "end", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("period_value")
    @classmethod
    def validate_period(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if len(text) not in (7, 10):
            raise ValueError("期间值格式应为 YYYY-MM 或 YYYY-MM-DD")
        return text


class JushuitanMonthlyQuerySchema(JushuitanSalesOutboundQuerySchema):
    """零售出库未税总金额（月度指标）取数参数。"""

    amount_source: str = Field(
        default="items.auto",
        max_length=64,
        description=(
            "取数口径：items.auto（默认，明细行内先金额、再买家实付、后卖家实收）/"
            "order.pay_amount/order.paid_amount/items.sale_amount/items.buyer_paid_amount/items.seller_income_amount"
        ),
    )
    auto_fields: list[str] | None = Field(
        default=None, description="items.auto 的兜底字段顺序，如 ['seller_income_amount','buyer_paid_amount','sale_amount']"
    )
    tax_rate: float = Field(default=0, ge=0, le=100, description="税率(%)，用于含税金额折算未税金额")
    tax_inclusive: bool = Field(default=True, description="接口金额是否为含税金额(true=按税率折算未税)")
    by_shop: bool = Field(default=False, description="是否按店铺拆分汇总")


class JushuitanSalesOutboundResultSchema(BaseModel):
    """销售出库查询结果。"""

    source_id: int = Field(..., description="聚水潭连接配置ID")
    begin: str = Field(..., description="实际起始时间")
    end: str = Field(..., description="实际结束时间")
    order_count: int = Field(default=0, description="出库单数")
    item_qty: float = Field(default=0, description="出库商品数量合计")
    tax_inclusive_amount: float = Field(default=0, description="含税金额合计")
    untaxed_amount: float = Field(default=0, description="未税金额合计")
    tax_rate: float = Field(default=0, description="折算使用的税率(%)")
    amount_source: str = Field(default="order.pay_amount", description="取数口径")
    rows: list[dict] = Field(default_factory=list, description="出库单明细（include_rows=true 时返回）")


class JushuitanMonthlySummarySchema(BaseModel):
    """零售出库未税总金额（月度指标）结果。"""

    period_value: str = Field(..., description="月度期间 YYYY-MM")
    order_count: int = Field(default=0, description="已出库单据数")
    item_qty: float = Field(default=0, description="出库商品数量合计")
    tax_inclusive_amount: float = Field(default=0, description="含税金额合计")
    untaxed_amount: float = Field(default=0, description="未税总金额")
    tax_rate: float = Field(default=0, description="折算使用的税率(%)")
    amount_source: str = Field(default="order.pay_amount", description="取数口径")
    by_shop: dict = Field(default_factory=dict, description="按店铺汇总")
