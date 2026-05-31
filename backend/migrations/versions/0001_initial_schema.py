"""Initial schema: models, model_versions, instances

Revision ID: 0001
Revises:
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Create PG enum types idempotently (PostgreSQL does not support IF NOT EXISTS for types)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE visibility_enum AS ENUM ('public', 'protected');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE model_status_enum AS ENUM ('draft', 'published', 'unpublished');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    # Use raw DDL to avoid sa.Enum auto-CREATE TYPE collision with asyncpg
    op.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(256) NOT NULL,
            description TEXT,
            json_schema JSONB NOT NULL,
            system_prompt TEXT,
            enabled_tool_classes JSONB NOT NULL DEFAULT '[]'::jsonb,
            metrics_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            visibility visibility_enum NOT NULL DEFAULT 'public',
            api_key_hash VARCHAR(256),
            owner_sub VARCHAR(256) NOT NULL,
            status model_status_enum NOT NULL DEFAULT 'draft',
            current_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS model_versions (
            id VARCHAR(36) PRIMARY KEY,
            model_id VARCHAR(128) NOT NULL REFERENCES models(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            json_schema JSONB NOT NULL,
            system_prompt TEXT,
            enabled_tool_classes JSONB NOT NULL,
            metrics_config JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_model_versions_model_id ON model_versions(model_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            id VARCHAR(36) PRIMARY KEY,
            model_id VARCHAR(128) NOT NULL REFERENCES models(id) ON DELETE CASCADE,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_instances_model_id ON instances(model_id)")
    # GIN index for JSONB queries on instance data
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_instances_data_gin ON instances USING gin(data)"
    )
    # Partial index: only alive (non-deleted) instances
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_instances_model_alive
        ON instances(model_id, created_at)
        WHERE deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS instances")
    op.execute("DROP TABLE IF EXISTS model_versions")
    op.execute("DROP TABLE IF EXISTS models")
    op.execute("DROP TYPE IF EXISTS model_status_enum")
    op.execute("DROP TYPE IF EXISTS visibility_enum")
