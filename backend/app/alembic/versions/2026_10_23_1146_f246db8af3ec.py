"""兼容迁移：去掉 ``open_client.allow_retail_sync`` 的服务器默认值。

``retailpush01`` 已在新建列时直接使用 NOT NULL 且不保留 server_default；
本迁移用于兼容曾在开发库上应用过「带 DEFAULT 0」早期草稿的环境，确保
模型与库结构一致，避免 dev 自动迁移反复生成差异。

Revision ID: f246db8af3ec
Revises: retailpush01
Create Date: 2026-10-23 11:46:26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f246db8af3ec"
down_revision: str | None = "retailpush01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.alter_column(
            "allow_retail_sync",
            existing_type=sa.Boolean(),
            server_default=None,
            existing_nullable=False,
            existing_comment="是否允许推送零售数据(默认不开放)",
        )


def downgrade() -> None:
    # 不恢复默认值：降级后由 retailpush01 直接删除该列，无需中间态默认值
    pass
