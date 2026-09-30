from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class JushuitanConnectionModel(ModelMixin, UserMixin):
    """聚水潭开放平台连接配置。"""

    __tablename__: str = "erp_jushuitan_connection"
    __table_args__: dict[str, str] = {"comment": "聚水潭开放平台连接配置表"}

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="连接名称")
    base_url: Mapped[str] = mapped_column(
        String(255), default="https://openapi.jushuitan.com", nullable=False, comment="接口地址(正式/测试环境)"
    )
    app_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="开发者应用app_key")
    app_secret: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="应用密钥(Fernet加密)")
    access_token: Mapped[str | None] = mapped_column(
        Text, default=None, nullable=True, comment="商家授权access_token(Fernet加密)"
    )
    shop_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="默认店铺编码(0=线下)")
    is_offline_shop: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="是否仅取线下店铺单据(0:否 1:是)"
    )
    timeout: Mapped[int] = mapped_column(Integer, default=30, nullable=False, comment="读取超时(秒)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")
