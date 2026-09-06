"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tables are created by SQLAlchemy metadata on API/worker startup.
    # This revision exists so Alembic has a baseline for later changes.
    op.execute("SELECT 1")


def downgrade() -> None:
    pass
