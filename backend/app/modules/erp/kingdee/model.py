from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class KingdeeConnectionModel(ModelMixin, UserMixin):
    """金蝶云星空 WebAPI 连接配置。"""

    __tablename__: str = "erp_kingdee_connection"
    __table_args__: dict[str, str] = {"comment": "金蝶云星空连接配置表"}

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="连接名称")
    server_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="服务地址(以 /k3cloud/ 结尾)")
    acct_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="账套ID")
    username: Mapped[str] = mapped_column(String(128), nullable=False, comment="授权用户")
    app_id: Mapped[str] = mapped_column(String(255), nullable=False, comment="应用ID")
    app_secret: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="应用密钥(Fernet加密)")
    lcid: Mapped[int] = mapped_column(Integer, default=2052, nullable=False, comment="账套语系")
    org_num: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="组织编码(多组织时启用)")
    connect_timeout: Mapped[int] = mapped_column(Integer, default=120, nullable=False, comment="连接超时(秒)")
    request_timeout: Mapped[int] = mapped_column(Integer, default=120, nullable=False, comment="读取超时(秒)")
    proxy: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True, comment="代理地址")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")
