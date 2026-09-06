"""Store qualifying GSM lists on assessments.

Revision ID: 003
Revises: 002
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if not _has_column("assessments", "qualifying_gsms_json"):
        op.add_column("assessments", sa.Column("qualifying_gsms_json", sa.Text(), server_default="[]"))


def downgrade() -> None:
    pass
