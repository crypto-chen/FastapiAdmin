from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class SourceSystemModel(ModelMixin, UserMixin):
    """外部来源系统注册表。"""

    __tablename__: str = "meta_source_system"
    __table_args__: dict[str, str] = {"comment": "来源系统元数据"}
    __data_scope_exempt__: bool = True

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="系统编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="系统名称")
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="连接器类型(kingdee/api/database/excel/other)")
    connection_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="连接配置ID")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")


class SourceObjectModel(ModelMixin, UserMixin):
    """来源对象/表单/表定义。"""

    __tablename__: str = "meta_source_object"
    __table_args__: tuple = (
        UniqueConstraint("system_id", "code", name="uq_meta_source_object"),
        {"comment": "来源对象元数据"},
    )
    __data_scope_exempt__: bool = True

    system_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_source_system.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源系统ID",
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="对象编码/表单Id")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="对象名称")
    query_type: Mapped[str] = mapped_column(String(32), nullable=False, default="bill_query", comment="查询类型(view/bill_query/api/database)")
    request_template: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="请求模板")
    variables: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="变量定义列表")
    watermark_field: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="增量水位字段")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")


class SourceFieldModel(ModelMixin, UserMixin):
    """来源字段定义。"""

    __tablename__: str = "meta_source_field"
    __table_args__: tuple = (
        UniqueConstraint("object_id", "field_key", name="uq_meta_source_field"),
        {"comment": "来源字段元数据"},
    )
    __data_scope_exempt__: bool = True

    object_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_source_object.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源对象ID",
    )
    field_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="字段Key")
    field_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="字段名称")
    data_type: Mapped[str] = mapped_column(String(32), default="string", nullable=False, comment="数据类型")
    is_primary_key: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否主键")
    is_watermark: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否增量水位")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")


class StandardEntityModel(ModelMixin, UserMixin):
    """标准实体定义。"""

    __tablename__: str = "meta_standard_entity"
    __table_args__: dict[str, str] = {"comment": "标准实体元数据"}
    __data_scope_exempt__: bool = True

    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True, comment="标准实体编码")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="标准实体名称")
    table_name: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="目标物理表")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")


class StandardFieldModel(ModelMixin, UserMixin):
    """标准字段定义。"""

    __tablename__: str = "meta_standard_field"
    __table_args__: tuple = (
        UniqueConstraint("entity_id", "field_code", name="uq_meta_standard_field"),
        {"comment": "标准字段元数据"},
    )
    __data_scope_exempt__: bool = True

    entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_standard_entity.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="标准实体ID",
    )
    field_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="标准字段编码")
    field_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="标准字段名称")
    data_type: Mapped[str] = mapped_column(String(32), default="string", nullable=False, comment="数据类型")
    is_dimension: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否维度")
    is_measure: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否度量")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")


class FieldMappingModel(ModelMixin, UserMixin):
    """来源字段到标准字段的映射与加工规则。"""

    __tablename__: str = "meta_field_mapping"
    __table_args__: dict[str, str] = {"comment": "字段映射元数据"}
    __data_scope_exempt__: bool = True

    source_object_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_source_object.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源对象ID",
    )
    source_field_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_source_field.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源字段ID",
    )
    standard_field_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_standard_field.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="标准字段ID",
    )
    transform_type: Mapped[str] = mapped_column(String(32), default="direct", nullable=False, comment="加工类型")
    transform_config: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="加工配置")
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="执行顺序")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")


class MetaSyncJobModel(ModelMixin, UserMixin):
    """元数据同步任务（Cron 管理）。"""

    __tablename__: str = "meta_sync_job"
    __table_args__: dict[str, str] = {"comment": "元数据同步任务表"}
    __data_scope_exempt__: bool = True

    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="任务名称")
    source_system_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_source_system.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源系统ID",
    )
    source_object_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_source_object.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源对象ID",
    )
    standard_entity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("meta_standard_entity.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        comment="标准实体ID",
    )
    org_code: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="组织编码")
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False, comment="Cron表达式")
    request_params: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="请求参数/Model")
    variables: Mapped[list | None] = mapped_column(JSON, default=None, nullable=True, comment="任务级变量定义")
    sync_mode: Mapped[str] = mapped_column(String(16), default="full", nullable=False, comment="同步模式(full/incremental)")
    watermark_field: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="增量水位字段")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")


class MetaSyncRunModel(ModelMixin, UserMixin):
    """元数据同步运行日志。"""

    __tablename__: str = "meta_sync_run"
    __table_args__: dict[str, str] = {"comment": "元数据同步运行日志"}
    __data_scope_exempt__: bool = True

    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("meta_sync_job.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="同步任务ID",
    )
    batch_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True, comment="批次ID")
    period_value: Mapped[str | None] = mapped_column(
        String(32), default=None, nullable=True, index=True, comment="取数期间(如 2026-09；按期间回补时使用)"
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, comment="状态(pending/running/success/failed)")
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="行数")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True, comment="结束时间")
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="错误信息")
    rows_json: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始返回数据")
