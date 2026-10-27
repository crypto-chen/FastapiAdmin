"""开放应用增加「允许读取平台渠道分析指标」开关。

``open_client.allow_platform_analysis``：默认 False（第三方调用
``/open/v1/retail/platform/analysis`` 返回 403），由管理端「开放接口应用」逐个应用开启。

Revision ID: retailplatform01
Revises: b0f396df56ac
Create Date: 2026-10-27 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "retailplatform01"
down_revision: str | None = "b0f396df56ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 存量行较多，先加可空列 → 回填 0 → 再收紧为 NOT NULL（MySQL 直接加 NOT NULL 无默认值会失败）
    op.add_column(
        "open_client",
        sa.Column(
            "allow_platform_analysis",
            sa.Boolean(),
            nullable=True,
            comment="是否允许读取平台渠道分析指标(默认不开放)",
        ),
    )
    op.execute(sa.text("UPDATE open_client SET allow_platform_analysis = 0 WHERE allow_platform_analysis IS NULL"))
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        # 与 allow_retail_sync 保持一致：不保留 server_default，避免 autogenerate 反复生成差异
        batch_op.alter_column(
            "allow_platform_analysis",
            existing_type=sa.Boolean(),
            existing_nullable=True,
            nullable=False,
            server_default=None,
            existing_comment="是否允许读取平台渠道分析指标(默认不开放)",
        )


def downgrade() -> None:
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.drop_column("allow_platform_analysis")
