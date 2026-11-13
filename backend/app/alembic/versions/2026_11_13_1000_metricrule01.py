"""指标口径版本与期间钉版。

Revision ID: metricrule01
Revises: wecomtoken01
Create Date: 2026-11-13 10:00:00
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "metricrule01"
down_revision: str | None = "wecomtoken01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_text(value):
    """JSON 列在不同驱动下可能返回 str/bytes/dict，统一成可写入的文本。"""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
    ]


def _user_fks(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["created_id"],
            ["sys_user.id"],
            name=op.f(f"fk_{table}_created_id_sys_user"),
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_id"],
            ["sys_user.id"],
            name=op.f(f"fk_{table}_updated_id_sys_user"),
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_id"],
            ["sys_user.id"],
            name=op.f(f"fk_{table}_deleted_id_sys_user"),
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "metric_def_version",
        sa.Column(
            "metric_id",
            sa.Integer(),
            sa.ForeignKey("metric_def.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
            comment="指标定义ID",
        ),
        sa.Column("version", sa.Integer(), nullable=False, comment="定义版本号"),
        sa.Column("effective_from", sa.Date(), nullable=False, comment="生效开始日期"),
        sa.Column("effective_to", sa.Date(), nullable=True, comment="生效结束日期"),
        sa.Column("code", sa.String(length=128), nullable=False, comment="指标编码"),
        sa.Column("name", sa.String(length=255), nullable=False, comment="指标名称"),
        sa.Column("category", sa.String(length=64), nullable=False, comment="指标分类"),
        sa.Column("excel_code", sa.String(length=64), nullable=True, comment="Excel 科目编码"),
        sa.Column("period_type", sa.String(length=16), nullable=False, comment="期间类型"),
        sa.Column("sensitivity", sa.Integer(), nullable=False, comment="敏感级别"),
        sa.Column("formula", sa.Text(), nullable=True, comment="计算公式"),
        sa.Column("dimensions", sa.JSON(), nullable=True, comment="维度配置"),
        sa.Column("measures", sa.JSON(), nullable=True, comment="度量配置"),
        sa.Column("source_entity_id", sa.Integer(), nullable=True, comment="来源标准实体ID"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态(0:启用 1:停用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注"),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_def_version")),
        sa.UniqueConstraint(
            "metric_id", "version", name="uq_metric_def_version_metric_version"
        ),
        *_user_fks("metric_def_version"),
        comment="指标定义版本表",
    )
    with op.batch_alter_table("metric_def_version", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_metric_def_version_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_metric_def_version_metric_id"), ["metric_id"], unique=False
        )
        batch_op.create_index(
            "ix_metric_def_version_effective", ["metric_id", "effective_from"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_metric_def_version_uuid"), ["uuid"], unique=True)
        batch_op.create_index(
            batch_op.f("ix_metric_def_version_is_deleted"), ["is_deleted"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_def_version_created_time"), ["created_time"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_def_version_created_id"), ["created_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_def_version_updated_id"), ["updated_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_def_version_deleted_id"), ["deleted_id"], unique=False
        )

    op.create_table(
        "metric_period_version",
        sa.Column("period_type", sa.String(length=16), nullable=False, comment="期间类型"),
        sa.Column("period_value", sa.String(length=32), nullable=False, comment="期间值"),
        sa.Column(
            "metric_id",
            sa.Integer(),
            sa.ForeignKey("metric_def.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
            comment="指标定义ID",
        ),
        sa.Column("pinned_def_version", sa.Integer(), nullable=False, comment="历史规则定义版本"),
        sa.Column("active_def_version", sa.Integer(), nullable=False, comment="当前生效定义版本"),
        sa.Column("last_calc_version", sa.Integer(), nullable=False, comment="最近计算版本"),
        sa.Column("last_rule_mode", sa.String(length=16), nullable=False, comment="最近计算口径模式"),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_period_version")),
        sa.UniqueConstraint(
            "period_type", "period_value", "metric_id", name="uq_metric_period_version_key"
        ),
        *_user_fks("metric_period_version"),
        comment="指标期间口径版本表",
    )
    with op.batch_alter_table("metric_period_version", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_metric_period_version_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_metric_id"), ["metric_id"], unique=False
        )
        batch_op.create_index(
            "ix_metric_period_version_period", ["period_type", "period_value"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_uuid"), ["uuid"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_is_deleted"), ["is_deleted"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_created_time"), ["created_time"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_created_id"), ["created_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_updated_id"), ["updated_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_metric_period_version_deleted_id"), ["deleted_id"], unique=False
        )

    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("metric_run")}
    if "rule_mode" not in columns:
        with op.batch_alter_table("metric_run", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "rule_mode",
                    sa.String(length=16),
                    nullable=False,
                    server_default="historical",
                    comment="口径模式(historical/current)",
                )
            )

    value_indexes = {
        index["name"] for index in inspect(op.get_bind()).get_indexes("metric_value")
    }
    if "ix_metric_value_metric_period_def_ver" not in value_indexes:
        op.create_index(
            "ix_metric_value_metric_period_def_ver",
            "metric_value",
            ["metric_id", "period_type", "period_value", "version", "calc_version"],
            unique=False,
        )

    # 存量指标补一条 v1 快照（1970-01-01 起生效），保证历史期间可解析到旧口径
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, version, code, name, category, excel_code, period_type, sensitivity, "
            "formula, dimensions, measures, source_entity_id, status, description "
            "FROM metric_def"
        )
    ).mappings().all()
    now = datetime.now(UTC)
    for row in rows:
        version = int(row["version"] or 1)
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM metric_def_version WHERE metric_id = :metric_id AND version = :version"
            ),
            {"metric_id": row["id"], "version": version},
        ).first()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO metric_def_version "
                "(metric_id, version, effective_from, effective_to, code, name, category, excel_code, "
                "period_type, sensitivity, formula, dimensions, measures, source_entity_id, status, description, "
                "uuid, is_deleted, created_time, updated_time, deleted_time) "
                "VALUES (:metric_id, :version, :effective_from, NULL, :code, :name, :category, :excel_code, "
                ":period_type, :sensitivity, :formula, :dimensions, :measures, :source_entity_id, :status, :description, "
                ":uuid, :is_deleted, :created_time, :updated_time, NULL)"
            ),
            {
                "metric_id": row["id"],
                "version": version,
                "effective_from": date(1970, 1, 1),
                "code": row["code"],
                "name": row["name"],
                "category": row["category"],
                "excel_code": row["excel_code"],
                "period_type": row["period_type"],
                "sensitivity": row["sensitivity"] or 0,
                "formula": row["formula"],
                "dimensions": _json_text(row["dimensions"]),
                "measures": _json_text(row["measures"]),
                "source_entity_id": row["source_entity_id"],
                "status": row["status"] or 0,
                "description": row["description"],
                "uuid": uuid.uuid4().hex,
                "is_deleted": False,
                "created_time": now,
                "updated_time": now,
            },
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("metric_run")}
    if "rule_mode" in columns:
        with op.batch_alter_table("metric_run", schema=None) as batch_op:
            batch_op.drop_column("rule_mode")
    op.drop_table("metric_period_version")
    op.drop_table("metric_def_version")
