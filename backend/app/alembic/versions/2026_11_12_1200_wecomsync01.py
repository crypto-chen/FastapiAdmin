"""新增企业微信通讯录/打卡同步相关表。

Revision ID: wecomsync01
Revises: 599052b1a95a
Create Date: 2026-11-12 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wecomsync01"
down_revision: str | None = "599052b1a95a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_wecom_connection",
        sa.Column("name", sa.String(length=64), nullable=False, comment="连接名称"),
        sa.Column("corp_id", sa.String(length=128), nullable=False, comment="企业ID(corpid)"),
        sa.Column("checkin_secret", sa.Text(), nullable=True, comment="打卡应用Secret(Fernet加密)"),
        sa.Column("contact_secret", sa.Text(), nullable=True, comment="通讯录Secret(Fernet加密)"),
        sa.Column("agent_id", sa.Integer(), nullable=True, comment="应用AgentId"),
        sa.Column("timeout", sa.Integer(), nullable=False, comment="读取超时(秒)"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态(0:启用 1:停用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
        sa.ForeignKeyConstraint(
            ["created_id"],
            ["sys_user.id"],
            name=op.f("fk_erp_wecom_connection_created_id_sys_user"),
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_id"],
            ["sys_user.id"],
            name=op.f("fk_erp_wecom_connection_deleted_id_sys_user"),
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_id"],
            ["sys_user.id"],
            name=op.f("fk_erp_wecom_connection_updated_id_sys_user"),
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_wecom_connection")),
        comment="企业微信连接配置表",
    )
    with op.batch_alter_table("erp_wecom_connection", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_created_id"), ["created_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_deleted_id"), ["deleted_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_name"), ["name"], unique=True)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_updated_id"), ["updated_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_erp_wecom_connection_uuid"), ["uuid"], unique=True)

    op.create_table(
        "wecom_checkin_day",
        sa.Column("userid", sa.String(length=64), nullable=False, comment="企微成员UserID(工号)"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="成员姓名"),
        sa.Column("work_date", sa.Date(), nullable=False, comment="打卡日期"),
        sa.Column("earliest_sec", sa.Integer(), nullable=True, comment="最早打卡(当日0点起秒数)"),
        sa.Column("latest_sec", sa.Integer(), nullable=True, comment="最晚打卡(当日0点起秒数)"),
        sa.Column("regular_work_sec", sa.Integer(), nullable=False, comment="当日实际工作时长(秒)"),
        sa.Column("off_work_sec", sa.Integer(), nullable=True, comment="当天规定下班时间(秒)"),
        sa.Column("cross_day", sa.Boolean(), nullable=False, comment="是否跨夜打卡"),
        sa.Column("raw_json", sa.JSON(), nullable=True, comment="企微原始日报数据"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, comment="同步时间"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wecom_checkin_day")),
        sa.UniqueConstraint("userid", "work_date", name="uq_wecom_checkin_day_userid_work_date"),
        comment="企业微信每日打卡记录表",
    )
    with op.batch_alter_table("wecom_checkin_day", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_wecom_checkin_day_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_checkin_day_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_checkin_day_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_checkin_day_userid"), ["userid"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_checkin_day_uuid"), ["uuid"], unique=True)
        batch_op.create_index(batch_op.f("ix_wecom_checkin_day_work_date"), ["work_date"], unique=False)

    op.create_table(
        "wecom_sync_run",
        sa.Column("sync_type", sa.String(length=32), nullable=False, comment="同步类型(roster/checkin)"),
        sa.Column("date_from", sa.Date(), nullable=True, comment="开始日期"),
        sa.Column("date_to", sa.Date(), nullable=True, comment="结束日期"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(running/success/partial/failed)"),
        sa.Column("expected_users", sa.Integer(), nullable=False, comment="应同步人数"),
        sa.Column("actual_users", sa.Integer(), nullable=False, comment="实际出数人数"),
        sa.Column("rows_upserted", sa.Integer(), nullable=False, comment="写入行数"),
        sa.Column("error_msg", sa.Text(), nullable=True, comment="错误摘要"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True, comment="结束时间"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wecom_sync_run")),
        comment="企业微信同步批次日志表",
    )
    with op.batch_alter_table("wecom_sync_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_wecom_sync_run_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_sync_run_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_sync_run_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_sync_run_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_sync_run_sync_type"), ["sync_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_wecom_sync_run_uuid"), ["uuid"], unique=True)


def downgrade() -> None:
    op.drop_table("wecom_sync_run")
    op.drop_table("wecom_checkin_day")
    op.drop_table("erp_wecom_connection")

