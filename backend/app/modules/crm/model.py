from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class CrmConnectionModel(ModelMixin, UserMixin):
    """CRM 开放接口连接配置（订单未税金额等指标的数据源）。"""

    __tablename__: str = "crm_connection"
    __table_args__: dict[str, str] = {"comment": "CRM 连接配置表"}

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="连接名称")
    base_url: Mapped[str] = mapped_column(
        String(255), default="http://crmapi.yonggubox.com", nullable=False, comment="接口域名"
    )
    timeout: Mapped[int] = mapped_column(Integer, default=30, nullable=False, comment="读取超时(秒)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")
