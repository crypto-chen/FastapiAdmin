"""平台分析指标配置表。

平台指标不再写死在代码里：页面的列、口径、排序、启停全部来自本表，
新增指标只需插入一行（公式用表达式描述），不需要改代码。
"""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class PlatformMetricModel(ModelMixin):
    """平台分析指标定义。"""

    __tablename__: str = "platform_metric_def"
    __table_args__: dict[str, str] = {"comment": "平台分析指标定义表"}
    __data_scope_exempt__: bool = True

    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True, comment="指标编码(如 PLT-08)"
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="指标名称")
    group: Mapped[str] = mapped_column(
        String(32), default="金额", nullable=False, comment="分组：维度/数量/金额/比率"
    )
    data_type: Mapped[str] = mapped_column(
        String(16), default="number", nullable=False, comment="数据类型：number/percent/string"
    )
    unit: Mapped[str | None] = mapped_column(String(16), default=None, nullable=True, comment="单位")
    sensitive: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否敏感字段（页面标红）"
    )
    expression: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=True,
        comment="取值表达式：可用 base 变量（orders/intake/shipment/...）与其他指标编码",
    )
    readiness: Mapped[str] = mapped_column(
        String(16),
        default="ready",
        nullable=False,
        comment="可出性：ready 现用可出 / pending 待确认 / todo 待做 / missing 缺数据源",
    )
    note: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="口径说明")
    sort: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="列顺序")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
