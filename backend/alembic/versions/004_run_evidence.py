"""Run-evidence association for shared evidence content.

Revision ID: 004
Revises: 003
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    rows = bind.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='run_evidence'").fetchall()
    return bool(rows)


def upgrade() -> None:
    if _has_table("run_evidence"):
        return
    op.create_table(
        "run_evidence",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("evidence_id", sa.String(40), sa.ForeignKey("evidence.id"), nullable=False),
        sa.Column("source_url", sa.Text(), server_default=""),
        sa.Column("field_path", sa.Text(), server_default=""),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("rebuilt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("run_id", "evidence_id", name="uq_run_evidence"),
    )
    op.create_index("ix_run_evidence_run_id", "run_evidence", ["run_id"])
    op.create_index("ix_run_evidence_evidence_id", "run_evidence", ["evidence_id"])


def downgrade() -> None:
    pass
