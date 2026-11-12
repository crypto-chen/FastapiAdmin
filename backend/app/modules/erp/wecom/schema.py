"""企业微信同步接口的请求/响应模型。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam
from app.modules.erp.wecom.calc import (
    DEFAULT_MARKETING_PREFIX,
    MAX_RANGE_DAYS,
)


class WeComConnectionCreateSchema(BaseModel):
    """企业微信连接配置创建模型。"""

    name: str = Field(..., min_length=1, max_length=64, description="连接名称")
    corp_id: str = Field(default="", max_length=128, description="企业ID(corpid)")
    checkin_secret: str | None = Field(default=None, max_length=512, description="打卡应用Secret")
    contact_secret: str | None = Field(default=None, max_length=512, description="通讯录Secret")
    token_url: str | None = Field(
        default=None,
        max_length=512,
        description="Token服务URL（PHP兼容模式，配置后免填Secret）",
    )
    agent_id: int | None = Field(default=None, ge=0, description="应用AgentId")
    timeout: int = Field(default=30, ge=1, le=300, description="读取超时(秒)")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("必填项不能为空")
        return value

    @field_validator("token_url")
    @classmethod
    def validate_token_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("Token服务URL必须以 http:// 或 https:// 开头")
        return value


class WeComConnectionUpdateSchema(BaseModel):
    """企业微信连接配置更新模型（Secret 为空表示不修改）。"""

    name: str = Field(..., min_length=1, max_length=64, description="连接名称")
    corp_id: str = Field(default="", max_length=128, description="企业ID(corpid)")
    checkin_secret: str | None = Field(default=None, max_length=512, description="打卡应用Secret")
    contact_secret: str | None = Field(default=None, max_length=512, description="通讯录Secret")
    token_url: str | None = Field(
        default=None,
        max_length=512,
        description="Token服务URL（为空表示不修改）",
    )
    agent_id: int | None = Field(default=None, ge=0, description="应用AgentId")
    timeout: int = Field(default=30, ge=1, le=300, description="读取超时(秒)")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, max_length=500, description="备注")

    @field_validator("name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("必填项不能为空")
        return value

    @field_validator("token_url")
    @classmethod
    def validate_token_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("Token服务URL必须以 http:// 或 https:// 开头")
        return value


class WeComConnectionOutSchema(BaseSchema):
    """企业微信连接配置输出模型（Secret 不返回）。"""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(description="连接名称")
    corp_id: str = Field(description="企业ID(corpid)")
    agent_id: int | None = Field(default=None, description="应用AgentId")
    timeout: int = Field(default=30, description="读取超时(秒)")
    status: int = Field(default=0, description="状态(0:启用 1:停用)")
    description: str | None = Field(default=None, description="备注")
    has_checkin_secret: bool = Field(default=False, description="是否已配置打卡Secret")
    has_contact_secret: bool = Field(default=False, description="是否已配置通讯录Secret")
    has_token_url: bool = Field(default=False, description="是否已配置Token服务URL")


class WeComConnectionQueryParam(BaseQueryParam, UserByQueryParam):
    """企业微信连接查询参数。"""

    name: str | None = Field(None, description="连接名称", json_schema_extra={"q": "like"})
    status: int | None = Field(None, ge=0, le=1, description="状态(0:启用 1:停用)", json_schema_extra={"q": "eq"})


class WeComEmployeeOutSchema(BaseModel):
    """企微人员输出模型。"""

    userid: str = Field(description="企微成员UserID(工号)")
    name: str = Field(description="姓名")
    mobile: str | None = Field(default=None, description="手机号")
    email: str | None = Field(default=None, description="邮箱")
    dept_code: str | None = Field(default=None, description="主部门编码")
    status: int = Field(default=0, description="状态(0:在职 1:离职/禁用)")
    updated_time: datetime | None = Field(default=None, description="更新时间")


class WeComCheckinOutSchema(BaseModel):
    """每人每天的打卡明细。"""

    userid: str = Field(description="企微成员UserID(工号)")
    name: str = Field(default="", description="姓名")
    work_date: date = Field(description="打卡日期")
    earliest_time: str = Field(description="最早打卡 HH:MM:SS")
    latest_time: str = Field(description="最晚打卡 HH:MM:SS")
    off_work_time: str = Field(description="规定下班时间 HH:MM:SS")
    regular_work_sec: int = Field(default=0, description="当日实际工作时长(秒)")
    regular_hours: float = Field(default=0, description="扣午休后的正常工时(小时)")
    overtime_sec: int = Field(default=0, description="加班秒数")
    overtime_hours: float = Field(default=0, description="加班小时")
    cross_day: bool = Field(default=False, description="是否跨夜打卡")


class WeComWorktimeResultSchema(BaseModel):
    """工时统计结果（兼容旧 PHP 字段，并补充按人/按天明细）。"""

    regularWorkHours: float = Field(description="正常上班时间(小时,已扣午休)")
    overtimeHours: float = Field(description="加班时间(小时)")
    regularWork: dict = Field(description="正常工时汇总与按人明细")
    overtime: dict = Field(description="加班汇总与按天明细")
    expectedUserCount: int = Field(default=0, description="应统计人数")
    userCount: int = Field(default=0, description="实际出数人数")
    byUser: list[dict] = Field(default_factory=list, description="按人汇总")
    byDay: list[dict] = Field(default_factory=list, description="按天明细")
    missingUsers: list[dict] = Field(default_factory=list, description="没有打卡数据的人员")
    warning: dict | None = Field(default=None, description="数据完整性告警")
    personSource: str = Field(default="crm", description="人员范围来源(crm/wecom)")


class WeComSyncRosterSchema(BaseModel):
    """同步通讯录参数。"""

    connection_id: int | None = Field(default=None, ge=1, description="连接配置ID；不传取第一个启用的连接")


class WeComSyncCheckinSchema(BaseModel):
    """同步打卡参数。"""

    start_date: date = Field(description="开始日期")
    end_date: date = Field(description="结束日期")
    connection_id: int | None = Field(default=None, ge=1, description="连接配置ID")
    userids: list[str] | None = Field(default=None, description="指定工号；不传取通讯录在职人员")
    only_marketing: bool = Field(default=False, description="只同步 YG20 开头的营销人员")

    @model_validator(mode="after")
    def validate_range(self) -> "WeComSyncCheckinSchema":
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        if (self.end_date - self.start_date).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"单次同步跨度不能超过 {MAX_RANGE_DAYS} 天")
        return self


class WeComSyncRunOutSchema(BaseSchema):
    """同步批次输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    sync_type: str = Field(description="同步类型")
    date_from: date | None = Field(default=None, description="开始日期")
    date_to: date | None = Field(default=None, description="结束日期")
    status: str = Field(description="状态")
    expected_users: int = Field(default=0, description="应同步人数")
    actual_users: int = Field(default=0, description="实际出数人数")
    rows_upserted: int = Field(default=0, description="写入行数")
    error_msg: str | None = Field(default=None, description="错误摘要")
    started_at: datetime = Field(description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")


class WeComWorktimeQuerySchema(BaseModel):
    """工时查询参数。"""

    start_date: date = Field(description="开始日期")
    end_date: date = Field(description="结束日期")
    marketing_only: bool = Field(default=True, description="只统计营销人员")
    prefix: str = Field(default=DEFAULT_MARKETING_PREFIX, max_length=16, description="营销人员工号前缀")

    @model_validator(mode="after")
    def validate_range(self) -> "WeComWorktimeQuerySchema":
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        if (self.end_date - self.start_date).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"单次查询跨度不能超过 {MAX_RANGE_DAYS} 天")
        return self

