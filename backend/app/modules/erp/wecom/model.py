"""企业微信同步相关数据模型。"""

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class WeComConnectionModel(ModelMixin, UserMixin):
    """企业微信连接配置。"""

    __tablename__: str = "erp_wecom_connection"
    __table_args__: dict[str, str] = {"comment": "企业微信连接配置表"}

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="连接名称")
    corp_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="企业ID(corpid)")
    checkin_secret: Mapped[str | None] = mapped_column(
        Text, default=None, nullable=True, comment="打卡应用Secret(Fernet加密)"
    )
    contact_secret: Mapped[str | None] = mapped_column(
        Text, default=None, nullable=True, comment="通讯录Secret(Fernet加密)"
    )
    token_url: Mapped[str | None] = mapped_column(
        Text, default=None, nullable=True, comment="Token服务URL(PHP兼容模式，免填Secret)"
    )
    agent_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="应用AgentId")
    timeout: Mapped[int] = mapped_column(Integer, default=30, nullable=False, comment="读取超时(秒)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")


class WeComCheckinDayModel(ModelMixin):
    """企业微信每日打卡记录（一人一天一条）。"""

    __tablename__: str = "wecom_checkin_day"
    __table_args__: tuple = (
        UniqueConstraint("userid", "work_date", name="uq_wecom_checkin_day_userid_work_date"),
        {"comment": "企业微信每日打卡记录表"},
    )

    userid: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="企微成员UserID(工号)")
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="成员姓名")
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="打卡日期")
    earliest_sec: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="最早打卡(当日0点起秒数)")
    latest_sec: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="最晚打卡(当日0点起秒数)")
    regular_work_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="当日实际工作时长(秒)")
    off_work_sec: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True, comment="当天规定下班时间(秒)")
    cross_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否跨夜打卡")
    raw_json: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="企微原始日报数据")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, comment="同步时间"
    )


class WeComSyncRunModel(ModelMixin):
    """企业微信同步批次日志。"""

    __tablename__: str = "wecom_sync_run"
    __table_args__: dict[str, str] = {"comment": "企业微信同步批次日志表"}

    sync_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="同步类型(roster/checkin)")
    date_from: Mapped[date | None] = mapped_column(Date, default=None, nullable=True, comment="开始日期")
    date_to: Mapped[date | None] = mapped_column(Date, default=None, nullable=True, comment="结束日期")
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="状态(running/success/partial/failed)")
    expected_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="应同步人数")
    actual_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="实际出数人数")
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="写入行数")
    error_msg: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="错误摘要")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, comment="开始时间"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True, comment="结束时间"
    )

