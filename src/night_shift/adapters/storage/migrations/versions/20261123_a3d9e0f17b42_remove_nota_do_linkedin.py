"""remove nota do linkedin do outreach

Revision ID: a3d9e0f17b42
Revises: e51c0ad3c6e7
Create Date: 2026-11-23 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3d9e0f17b42"
down_revision: str | None = "e51c0ad3c6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("outreach", schema=None) as batch_op:
        batch_op.drop_column("linkedin_note")


def downgrade() -> None:
    with op.batch_alter_table("outreach", schema=None) as batch_op:
        batch_op.add_column(sa.Column("linkedin_note", sa.String(length=300), nullable=True))
