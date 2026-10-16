"""产品线分析宽表与构建批次模型。

设计要点（与订单全链路 / 客户分析同构，详见 ``docs/营销中心产品线分析报表方案.md``）：

- ``dwd_product_line_analysis``：一行一「产品线大类 × SKU」一期间，
  ``period_value + product_line_code + sku + calc_version`` 唯一；
  核心字段（身份 / 金额 / 单量）用物理列，PRD-xx 其余字段统一放 ``extra`` JSON，加减字段零 DDL。
- ``dwd_product_line_build_run``：每次构建的批次记录（版本、产品线数、SKU 数、金额合计、质量标记）。

``is_aggregate``：0=产品线 × SKU 明细行、1=产品线小计行（sku 为空）、2=全表合计行。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class ProductLineAnalysisModel(ModelMixin, UserMixin):
    """产品线分析宽表（一行一产品线大类 × SKU 一期，按版本保留）。"""

    __tablename__: str = "dwd_product_line_analysis"
    __table_args__: tuple = (
        UniqueConstraint(
            "period_value", "product_line_code", "sku", "calc_version", name="uq_dwd_product_line_key"
        ),
        Index("ix_dwd_product_line_period", "period_value", "calc_version"),
        Index("ix_dwd_product_line_line", "product_line_code"),
        Index("ix_dwd_product_line_sku", "sku"),
        {"comment": "产品线分析宽表"},
    )
    __data_scope_exempt__: bool = True

    period_value: Mapped[str] = mapped_column(String(16), nullable=False, comment="期间(YYYY-MM)")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本")
    is_aggregate: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="0=明细 1=产品线小计 2=全表合计"
    )

    # 注意：这三列参与唯一键 uq_dwd_product_line_key(period_value, product_line_code, sku, calc_version)，
    # 长度必须收敛——utf8mb4 下 64+64 字符 ≈ 580 字节，能同时满足 InnoDB COMPACT(767) 与
    # 老版本/非 DYNAMIC 行格式(1000) 的索引键长上限；写成 128 会超限报
    # `Specified key was too long; max key length is 1000 bytes`。
    product_line_code: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="产品线大类（型号字典上卷原值）"
    )
    product_line_name: Mapped[str | None] = mapped_column(
        String(128), default=None, nullable=True, comment="产品线大类名称（同 code，便于展示）"
    )
    sku: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, comment="SKU（型号字典 model）"
    )

    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="订单数(接单量)")
    ship_qty: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="出货数量（订单全链路 ship_qty，待补）"
    )
    intake_untaxed: Mapped[float | None] = mapped_column(Numeric(20, 4), default=None, nullable=True, comment="接单未税")
    ship_untaxed: Mapped[float | None] = mapped_column(Numeric(20, 4), default=None, nullable=True, comment="货物出货未税")
    net_shipment: Mapped[float | None] = mapped_column(Numeric(20, 4), default=None, nullable=True, comment="对外出货净额")
    gross_profit: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="毛利（过渡列：订单全链路口径，PRD-41 底稿口径待定）"
    )
    contribution_margin: Mapped[float | None] = mapped_column(
        Numeric(20, 4),
        default=None,
        nullable=True,
        comment="边际贡献（过渡列：订单全链路口径，PRD-43 底稿口径待定）",
    )

    extra: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="PRD-xx 字段区(JSON)")
    data_quality_flag: Mapped[str | None] = mapped_column(
        String(128), default=None, nullable=True, comment="数据质量标记"
    )


class ProductLineBuildRunModel(ModelMixin, UserMixin):
    """产品线分析构建批次。"""

    __tablename__: str = "dwd_product_line_build_run"
    __table_args__: dict[str, str] = {"comment": "产品线分析构建批次"}
    __data_scope_exempt__: bool = True

    period_value: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="期间")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本")
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False, comment="状态")
    line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="产品线大类数(不含合计行)")
    sku_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="SKU 数")
    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="订单数")
    intake_untaxed_sum: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="接单未税合计"
    )
    net_shipment_sum: Mapped[float | None] = mapped_column(
        Numeric(20, 4), default=None, nullable=True, comment="对外出货净额合计"
    )
    matched_rows: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="命中型号字典的订单行数"
    )
    unmatched_rows: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="未命中型号字典的订单行数"
    )
    warnings: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="口径缺项提示")
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="错误信息")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True)
