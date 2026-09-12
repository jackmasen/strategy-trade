"""baseline v1.2.4 + P0 fixes + Trailing Stop + EMV short

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P0-4: users.must_change_password
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=True, server_default=sa.text("0"), comment="是否需要强制修改密码"),
    )

    # Trailing Stop: trade_positions 新增字段
    op.add_column(
        "trade_positions",
        sa.Column("trailing_enabled", sa.Integer(), nullable=True, server_default="0", comment="是否启用移动止损: 0-否 1-是"),
    )
    op.add_column(
        "trade_positions",
        sa.Column("trailing_activation_pct", sa.Float(), nullable=True, server_default="1.0", comment="激活移动止损的盈利百分比"),
    )
    op.add_column(
        "trade_positions",
        sa.Column("trailing_distance_pct", sa.Float(), nullable=True, server_default="0.5", comment="移动止损跟踪距离(%)"),
    )
    op.add_column(
        "trade_positions",
        sa.Column("trailing_high_price", sa.DECIMAL(18, 8), nullable=True, comment="持仓期间最高价(多)/最低价(空)"),
    )


def downgrade() -> None:
    op.drop_column("trade_positions", "trailing_high_price")
    op.drop_column("trade_positions", "trailing_distance_pct")
    op.drop_column("trade_positions", "trailing_activation_pct")
    op.drop_column("trade_positions", "trailing_enabled")
    op.drop_column("users", "must_change_password")
