"""Add scenarios table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # status is VARCHAR not a PG enum — simpler, sufficient for Phase 4
    op.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id VARCHAR(36) PRIMARY KEY,
            model_id VARCHAR(128) NOT NULL REFERENCES models(id) ON DELETE CASCADE,
            name VARCHAR(256) NOT NULL,
            -- Snapshot of live instance data at create_scenario time (list of {id, data})
            base_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- User-applied changes: [{op, instance_id?, data?}]
            changes JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- "active" | "computing" | "done"
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            -- Cached result of the last compute_metrics call
            computed_results JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_scenarios_model_id ON scenarios(model_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scenarios")
