"""submissions write-ahead history

Revision ID: 0002_submissions
Revises: 0001_initial
Create Date: 2026-07-03 00:00:00
"""
from alembic import op

revision = "0002_submissions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            console_id VARCHAR(64) PRIMARY KEY,
            coev2_job_id VARCHAR(200) NOT NULL,
            kind VARCHAR(40) NOT NULL,
            submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_status VARCHAR(80),
            last_seen_score FLOAT,
            idempotency_key VARCHAR(80) NOT NULL UNIQUE
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS submissions")
