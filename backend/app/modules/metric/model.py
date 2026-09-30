from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class MetricDefModel(ModelMixin, UserMixin):
    """指标定义。"""

    __tablename__: str = "metric_def"
    __table_args__: dict[str, str] = {"comment": "指标定义表"}
    __data_scope_exempt__: bool = True

    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True, comment="指标编码")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="指标名称")
    excel_code: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, index=True, comment="Excel 科目编码（财务口径对照编码）"
    )
    period_type: Mapped[str] = mapped_column(String(16), default="month", nullable=False, comment="期间类型(day/week/month/year)")
    sensitivity: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="敏感级别(0普通 1敏感 2机密)")
    formula: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="计算公式")
    dimensions: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="维度配置")
    measures: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="度量配置")
    source_entity_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="来源标准实体ID")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="版本号")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")


class MetricRunModel(ModelMixin, UserMixin):
    """指标计算批次。"""

    __tablename__: str = "metric_run"
    __table_args__: dict[str, str] = {"comment": "指标计算批次表"}
    __data_scope_exempt__: bool = True

    metric_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("metric_def.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="指标定义ID",
    )
    period_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="期间类型")
    period_value: Mapped[str] = mapped_column(String(32), nullable=False, comment="期间值")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="指标版本")
    batch_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="同步批次ID")
    filter_signature: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True, comment="过滤条件签名")
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, comment="状态(pending/running/success/failed)")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="结束时间")


class MetricValueModel(ModelMixin, UserMixin):
    """指标结果。"""

    __tablename__: str = "metric_value"
    __table_args__: dict[str, str] = {"comment": "指标结果表"}
    __data_scope_exempt__: bool = True

    metric_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("metric_def.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="指标定义ID",
    )
    run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("metric_run.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="计算批次ID",
    )
    period_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="期间类型")
    period_value: Mapped[str] = mapped_column(String(32), nullable=False, comment="期间值")
    org_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, index=True, comment="组织ID")
    dept_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, index=True, comment="部门ID")
    dept_code: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, index=True, comment="核算维度部门编码(原始，未映射也保留)"
    )
    dept_name: Mapped[str | None] = mapped_column(
        String(255), default=None, nullable=True, comment="核算维度部门名称(原始)"
    )
    person_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, index=True, comment="人员ID")
    value: Mapped[float] = mapped_column(Numeric(20, 4), default=0, nullable=False, comment="指标值")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="指标版本")
    calc_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="计算版本")
    batch_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="同步批次ID")
    filter_signature: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True, comment="过滤条件签名")
    calc_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="计算时间")


class MetricTraceModel(ModelMixin, UserMixin):
    """指标结果穿透追溯明细。"""

    __tablename__: str = "metric_trace"
    __table_args__: dict[str, str] = {"comment": "指标追溯表"}
    __data_scope_exempt__: bool = True

    metric_run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("metric_run.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="计算批次ID",
    )
    metric_value_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("metric_value.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="指标结果ID",
    )
    dwd_row_id: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, index=True, comment="标准明细行ID")
    source_batch_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, comment="来源批次ID")
    source_object_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="来源对象ID")
    source_pk: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="来源主键")
