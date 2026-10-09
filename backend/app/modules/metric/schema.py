from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.base_schema import BaseQueryParam, BaseSchema, UserByQueryParam, UserBySchema
from app.core.validator import DateTimeCNStr


class MetricDefCreateSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, description="指标编码")
    name: str = Field(..., min_length=1, max_length=255, description="指标名称")
    category: str = Field(default="营销中心-主表", min_length=1, max_length=64, description="指标分类")
    excel_code: str | None = Field(default=None, max_length=64, description="Excel 科目编码（财务口径对照编码）")
    period_type: str = Field(default="month", min_length=1, max_length=16, description="期间类型")
    sensitivity: int = Field(default=0, ge=0, le=2, description="敏感级别(0普通 1敏感 2机密)")
    formula: str | None = Field(default=None, max_length=4000, description="计算公式")
    dimensions: dict | None = Field(default=None, description="维度配置")
    measures: dict | None = Field(default=None, description="度量配置")
    source_entity_id: int | None = Field(default=None, ge=1, description="来源标准实体ID")
    status: int = Field(default=0, ge=0, le=1, description="状态(0:启用 1:停用)")
    # 备注实际承载「指标口径说明」（数据来源 + 映射链 + 重算约定），与 formula 同为 Text 列，写入上限放宽
    description: str | None = Field(default=None, max_length=4000, description="备注")

    @field_validator("code", "name", "category", "period_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("指标编码、名称、分类、期间类型不能为空")
        return value


class MetricDefUpdateSchema(MetricDefCreateSchema):
    pass


class MetricDefOutSchema(MetricDefCreateSchema, BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    # 输出不做长度校验：库中 ``description`` 是 Text，初始化脚本会直写长口径说明
    # （seed_crm_person_metrics.py 实测 508 字），沿用写入上限会让整个分页查询 500，
    # 前端表现为「组件渲染异常」。
    description: str | None = Field(default=None, description="备注")

    version: int = Field(default=1, description="版本号")
    source_entity_code: str | None = Field(default=None, description="标准实体编码")
    source_entity_name: str | None = Field(default=None, description="标准实体名称")


class MetricDefQueryParam(BaseQueryParam, UserByQueryParam):
    code: str | None = Field(None, description="指标编码", json_schema_extra={"q": "like"})
    name: str | None = Field(None, description="指标名称", json_schema_extra={"q": "like"})
    category: str | None = Field(None, description="指标分类", json_schema_extra={"q": "like"})
    excel_code: str | None = Field(None, description="Excel 科目编码", json_schema_extra={"q": "like"})
    period_type: str | None = Field(None, description="期间类型", json_schema_extra={"q": "eq"})
    sensitivity: int | None = Field(None, ge=0, le=2, description="敏感级别", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, ge=0, le=1, description="状态", json_schema_extra={"q": "eq"})


class MetricValueQueryParam(BaseQueryParam):
    """指标结果查询参数；不传 ``calc_version`` 时默认只返回最新一次计算的版本。"""

    metric_id: int | None = Field(None, ge=1, description="指标定义ID", json_schema_extra={"q": "eq"})
    period_type: str | None = Field(None, description="期间类型", json_schema_extra={"q": "eq"})
    period_value: str | None = Field(None, description="期间值", json_schema_extra={"q": "eq"})
    org_id: int | None = Field(None, ge=1, description="组织ID", json_schema_extra={"q": "eq"})
    dept_id: int | None = Field(None, ge=1, description="核算维度（部门/客户）ID", json_schema_extra={"q": "eq"})
    calc_version: int | None = Field(None, ge=1, description="计算版本", json_schema_extra={"q": "eq"})
    level: Literal["org", "dept", "person", "all"] = Field(
        default="org",
        description="展示层级：org=仅组织合计 dept=仅核算维度明细 person=仅业务员明细 "
        "all=全部（由服务层翻译，不参与等值过滤）",
    )


class MetricValueOutSchema(BaseSchema, UserBySchema):
    model_config = ConfigDict(from_attributes=True)

    metric_id: int = Field(..., description="指标定义ID")
    run_id: int | None = Field(default=None, description="计算批次ID")
    period_type: str = Field(..., description="期间类型")
    period_value: str = Field(..., description="期间值")
    org_id: int | None = Field(default=None, description="组织ID")
    dept_id: int | None = Field(default=None, description="部门ID")
    dept_code: str | None = Field(default=None, description="核算维度编码(原始)")
    person_id: int | None = Field(default=None, description="人员ID")
    person_code: str | None = Field(default=None, description="业务员编码(原始)")
    person_name: str | None = Field(default=None, description="业务员姓名(原始)")
    value: float = Field(default=0, description="指标值")
    version: int = Field(default=1, description="指标版本")
    calc_version: int = Field(default=1, description="计算版本")
    batch_id: str | None = Field(default=None, description="计算批次ID")
    filter_signature: str | None = Field(default=None, description="取数条件签名")
    calc_time: DateTimeCNStr | None = Field(default=None, description="计算时间(北京时间)")
    org_code: str | None = Field(default=None, description="组织编码")
    org_name: str | None = Field(default=None, description="组织名称")
    dept_name: str | None = Field(default=None, description="核算维度名称")


class MetricCalcRequestSchema(BaseModel):
    period_value: str | None = Field(default=None, max_length=32, description="期间值，缺省取当前期间")
    org_codes: list[str] | None = Field(default=None, description="限定组织编码，缺省为全部组织")


class MetricMatrixQueryParam(BaseModel):
    """指标表单（多指标并排）查询参数。"""

    metric_ids: str = Field(..., min_length=1, description="指标定义ID，多个用英文逗号分隔")
    period_type: str | None = Field(default=None, description="期间类型；缺省按各指标自身期间类型")
    period_value: str | None = Field(default=None, description="期间值")
    org_id: int | None = Field(default=None, ge=1, description="组织ID")
    level: Literal["org", "dept", "person", "all"] = Field(
        default="org",
        description="展示层级：org=仅组织合计 dept=仅核算维度明细 person=仅业务员明细 all=全部",
    )
    page_no: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=500, ge=1, le=2000, description="每页数量（表单为整行返回，上限放宽）")


class MetricMatrixColumnSchema(BaseModel):
    """指标表单的列定义（一列一个指标）。"""

    metric_id: int = Field(..., description="指标定义ID")
    code: str = Field(..., description="指标编码")
    name: str = Field(..., description="指标名称")
    period_type: str = Field(..., description="期间类型")
    description: str | None = Field(default=None, description="口径说明（悬浮展示）")


class MetricMatrixRowSchema(BaseModel):
    """指标表单的一行（一个期间+组织+核算维度组合）。"""

    row_key: str = Field(..., description="行唯一键")
    period_value: str = Field(..., description="期间值")
    org_id: int | None = Field(default=None, description="组织ID")
    org_code: str | None = Field(default=None, description="组织编码")
    org_name: str | None = Field(default=None, description="组织名称")
    dept_id: int | None = Field(default=None, description="核算维度ID")
    dept_code: str | None = Field(default=None, description="核算维度编码")
    dept_name: str | None = Field(default=None, description="核算维度名称")
    person_id: int | None = Field(default=None, description="业务员人员ID")
    person_code: str | None = Field(default=None, description="业务员编码")
    person_name: str | None = Field(default=None, description="业务员姓名")
    values: dict[str, float] = Field(default_factory=dict, description="指标值，键为指标ID")
    calc_versions: dict[str, int] = Field(default_factory=dict, description="各指标计算版本，键为指标ID")
    calc_times: dict[str, DateTimeCNStr | None] = Field(
        default_factory=dict, description="各指标计算时间(北京时间)，键为指标ID"
    )


class MetricMatrixResultSchema(BaseModel):
    """指标表单查询结果：列定义 + 按组织/维度并排的结果行。"""

    columns: list[MetricMatrixColumnSchema] = Field(default_factory=list, description="指标列")
    items: list[MetricMatrixRowSchema] = Field(default_factory=list, description="结果行")
    page_no: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=500, description="每页数量")
    total: int = Field(default=0, description="总行数")
    has_next: bool = Field(default=False, description="是否有下一页")


class MetricBatchRunRequestSchema(BaseModel):
    """批量重算请求：不传 ``metric_ids`` / ``codes`` 时重算全部启用指标。"""

    metric_ids: list[int] | None = Field(default=None, description="要重算的指标定义ID")
    codes: list[str] | None = Field(default=None, description="要重算的指标编码")
    period_value: str | None = Field(default=None, max_length=32, description="期间值，缺省取当前期间")


class MetricBatchResultSchema(BaseModel):
    """批量重算结果摘要（按依赖分层执行）。"""

    label: str = Field(default="", description="批次标签")
    period: str | None = Field(default=None, description="期间值")
    metric_count: int = Field(default=0, description="参与计算的指标数")
    layer_count: int = Field(default=0, description="依赖分层数")
    success: int = Field(default=0, description="成功指标数")
    failed: list[str] = Field(default_factory=list, description="失败明细")
    problems: list[str] = Field(default_factory=list, description="依赖配置问题")
    elapsed_seconds: float = Field(default=0, description="耗时(秒)")
    totals: dict[str, float] = Field(default_factory=dict, description="各指标合计，键为指标编码")
    results: list[dict] = Field(default_factory=list, description="各指标计算结果明细")


class MetricCalcResultSchema(BaseModel):
    metric_id: int = Field(..., description="指标定义ID")
    metric_code: str = Field(..., description="指标编码")
    period_type: str = Field(..., description="期间类型")
    period_value: str = Field(..., description="期间值")
    calc_version: int = Field(..., description="计算版本")
    batch_id: str = Field(..., description="计算批次ID")
    partial: bool = Field(default=False, description="是否按组织范围部分重算")
    backfilled_orgs: list[str] = Field(default_factory=list, description="该期间缺批次、已按期间回补取数的组织")
    backfilled_components: list[str] = Field(
        default_factory=list, description="汇总指标：该期间缺结果、已临时补算的组成指标"
    )
    org_count: int = Field(default=0, description="参与计算的组织数")
    skipped_orgs: list[str] = Field(default_factory=list, description="无同步数据被跳过的组织")
    skipped: bool = Field(default=False, description="是否跳过计算（如指标未配置取数规则）")
    reason: str | None = Field(default=None, description="跳过计算的原因")
    total: float = Field(default=0, description="全部组织合计")
    orgs: dict = Field(default_factory=dict, description="各组织计算结果")
