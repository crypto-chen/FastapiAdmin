"""订单全链路宽表与构建批次模型。

设计要点（详见 ``docs/订单全链路数据方案.md``）：

- 一行一单，``order_number + calc_version`` 唯一；重算新增版本、不覆盖历史。
- 核心字段（订单号、期间、节点日期、主干金额、审计）用物理列；
  会随业务调整的字段统一放 ``extra`` JSON，加减字段零 DDL。
"""

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class OrderFullChainModel(ModelMixin, UserMixin):
    """订单全链路宽表（一行一单，按版本保留）。"""

    __tablename__: str = "dwd_order_full_chain"
    __table_args__: tuple = (
        UniqueConstraint("order_number", "calc_version", name="uq_dwd_order_full_chain_order_version"),
        Index("ix_dwd_order_full_chain_updated", "updated_time"),
        {"comment": "订单全链路宽表"},
    )
    __data_scope_exempt__: bool = True

    # ---- 主键与版本 ----
    order_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="CRM 订单号")
    period_value: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="期间(接单月 YYYY-MM)")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本(重算递增)")

    # ---- 订单属性 ----
    trade_type: Mapped[str | None] = mapped_column(
        String(16), default=None, nullable=True, index=True, comment="贸易类型(domestic/export)"
    )
    order_type: Mapped[str | None] = mapped_column(String(16), default=None, nullable=True, comment="订单类型(1批量 2打样 3零售)")
    customer_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="CRM 客户ID")
    salesman_code: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="业务员编码(CRM create_id)")
    order_date: Mapped[date | None] = mapped_column(Date, default=None, nullable=True, comment="接单日期")

    # ---- 节点日期 ----
    push_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="下推日期")
    finish_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True, comment="齐套入库日期")
    ship_date: Mapped[datetime | None] = mapped_column(
        DateTime, default=None, nullable=True, index=True, comment="销售出库日期"
    )

    # ---- 主干金额 ----
    qty: Mapped[float | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="数量")
    intake_untaxed: Mapped[float | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="接单未税")
    ship_untaxed: Mapped[float | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="出货未税")
    net_shipment: Mapped[float | None] = mapped_column(Numeric(18, 4), default=None, nullable=True, comment="净出货")

    # ---- 可变字段区 ----
    extra: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="可变字段区(JSON)")

    # ---- 审计与质量 ----
    source_batch_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="来源批次ID")
    data_quality_flag: Mapped[str | None] = mapped_column(
        String(32), default=None, nullable=True, comment="数据质量标记(ok/cost_missing/mo_unlinked/ar_customer_level)"
    )


class OrderBuildRunModel(ModelMixin, UserMixin):
    """订单全链路构建批次（记录每个期间每次重算的取数与质量指标）。"""

    __tablename__: str = "dwd_order_build_run"
    __table_args__: dict[str, str] = {"comment": "订单全链路构建批次"}
    __data_scope_exempt__: bool = True

    period_value: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="期间")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本")
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False, comment="状态(pending/running/success/failed)")
    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="订单数")
    mo_linked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="关联到生产订单的订单数")
    cost_missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="成本缺失订单数")
    source_batches: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="来源批次清单")
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="错误信息")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="结束时间")
