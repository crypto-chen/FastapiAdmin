"""客户分析宽表与构建批次模型。

设计要点（与订单全链路同构，详见 ``docs/营销中心客户分析报表方案.md``）：

- ``dwd_customer_analysis``：一行一客户一期间，``customer_code + period_value + calc_version`` 唯一；
  核心字段（身份/金额/单量）用物理列，CUS-xx 其余字段统一放 ``extra`` JSON，加减字段零 DDL。
- ``dwd_customer_build_run``：每次构建的批次记录（版本、客户数、金额合计、质量标记）。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class CustomerAnalysisModel(ModelMixin, UserMixin):
    """客户分析宽表（一行一客户一期，按版本保留）。"""

    __tablename__: str = "dwd_customer_analysis"
    __table_args__: tuple = (
        UniqueConstraint(
            "period_value", "customer_code", "calc_version", name="uq_dwd_customer_analysis_key"
        ),
        Index("ix_dwd_customer_analysis_period", "period_value", "calc_version"),
        Index("ix_dwd_customer_analysis_customer", "customer_code"),
        {"comment": "客户分析宽表"},
    )
    __data_scope_exempt__: bool = True

    period_value: Mapped[str] = mapped_column(String(16), nullable=False, comment="期间(YYYY-MM)")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本")
    is_aggregate: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="是否合计行(1 是)")

    customer_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="CRM 客户ID")
    customer_code: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="客户编码")
    customer_name: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True, comment="客户名称")
    salesman_code: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="业务员编码")
    salesman_name: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True, comment="业务员姓名")

    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="订单数(接单量)")
    intake_untaxed: Mapped[float | None] = mapped_column(Numeric(20, 4), default=None, nullable=True, comment="接单未税")
    net_shipment: Mapped[float | None] = mapped_column(Numeric(20, 4), default=None, nullable=True, comment="对外出货净额")
    gross_profit: Mapped[float | None] = mapped_column(Numeric(20, 4), default=None, nullable=True, comment="毛利")
    contribution_margin: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="边际贡献"
    )

    extra: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="CUS-xx 字段区(JSON)")
    data_quality_flag: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="数据质量标记"
    )


class CustomerBuildRunModel(ModelMixin, UserMixin):
    """客户分析构建批次。"""

    __tablename__: str = "dwd_customer_build_run"
    __table_args__: dict[str, str] = {"comment": "客户分析构建批次"}
    __data_scope_exempt__: bool = True

    period_value: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="期间")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本")
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False, comment="状态")
    customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="客户数(不含合计行)")
    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="订单数")
    intake_untaxed_sum: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="接单未税合计"
    )
    net_shipment_sum: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="对外出货净额合计"
    )
    master_customer_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="客户主档总数(时点)"
    )
    warnings: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="口径缺项提示")
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="错误信息")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True)
