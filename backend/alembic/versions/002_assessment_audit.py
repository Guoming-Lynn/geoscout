"""Add assessment/query audit columns for v0.1 fix round.

Revision ID: 002
Revises: 001
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if not _has_column("query_attempts", "truncated"):
        op.add_column("query_attempts", sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()))
    if not _has_column("assessments", "judge_source"):
        op.add_column("assessments", sa.Column("judge_source", sa.String(length=40), server_default=""))
    if not _has_column("assessments", "actor"):
        op.add_column("assessments", sa.Column("actor", sa.String(length=40), server_default=""))
    if not _has_column("assessments", "quotes_json"):
        op.add_column("assessments", sa.Column("quotes_json", sa.Text(), server_default="[]"))
    if not _has_column("assessments", "support_text"):
        op.add_column("assessments", sa.Column("support_text", sa.Text(), server_default=""))
    if not _has_column("assessments", "clue_only"):
        op.add_column("assessments", sa.Column("clue_only", sa.Boolean(), nullable=False, server_default=sa.false()))
    if not _has_column("samples", "group_label"):
        op.add_column("samples", sa.Column("group_label", sa.String(length=200), nullable=True))


def downgrade() -> None:
    pass
