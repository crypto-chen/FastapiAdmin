from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class OpenClientModel(ModelMixin, UserMixin):
    """开放接口接入应用（外部系统调用方）。"""

    __tablename__: str = "open_client"
    __table_args__: dict[str, str] = {"comment": "开放接口接入应用表"}
    __data_scope_exempt__: bool = True

    app_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="应用标识")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="应用名称")
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密钥哈希(PBKDF2，不可逆)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    ip_whitelist: Mapped[str | None] = mapped_column(
        String(500), default=None, nullable=True, comment="调用方 IP 白名单，逗号分隔，空=不限制"
    )
    token_ttl_seconds: Mapped[int] = mapped_column(Integer, default=7200, nullable=False, comment="令牌有效期(秒)")
    rate_limit: Mapped[int] = mapped_column(Integer, default=600, nullable=False, comment="每分钟最大请求数")
    allow_dept_detail: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否允许查询核算维度明细(默认仅组织合计)"
    )
    allow_run_calc: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否允许触发指标重算"
    )
    org_scope: Mapped[list | None] = mapped_column(
        JSON, default=None, nullable=True, comment="允许的组织编码列表，空=全部启用组织"
    )
    expire_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True, comment="凭证到期时间，空=长期有效"
    )
    contact: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="联系人")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="用途备注")


class OpenApiLogModel(ModelMixin, UserMixin):
    """开放接口调用日志。"""

    __tablename__: str = "open_api_log"
    __table_args__: dict[str, str] = {"comment": "开放接口调用日志表"}
    __data_scope_exempt__: bool = True

    client_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, index=True, comment="应用ID")
    app_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="应用标识")
    path: Mapped[str] = mapped_column(String(255), nullable=False, comment="请求路径")
    method: Mapped[str] = mapped_column(String(16), nullable=False, comment="请求方法")
    params: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="请求参数(已脱敏)")
    response_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="业务状态码")
    http_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False, comment="HTTP 状态码")
    cost_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="耗时(毫秒)")
    client_ip: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="调用方 IP")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="接口说明")
