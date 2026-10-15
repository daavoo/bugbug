"""Record the Otari key a run used and what the run spent through it.

Revision ID: d2e6b7a9c4f1
Revises: a7d4e9c21b83
Create Date: 2026-10-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e6b7a9c4f1"
down_revision: Union[str, Sequence[str], None] = "a7d4e9c21b83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("runs", sa.Column("otari_key_id", sa.String(), nullable=True))
    op.add_column("runs", sa.Column("llm_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "llm_cost_usd")
    op.drop_column("runs", "otari_key_id")
