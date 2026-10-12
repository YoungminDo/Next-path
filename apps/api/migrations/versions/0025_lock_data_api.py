"""Close the Supabase Data API: the app reads and writes only through FastAPI (table owner), so
the PostgREST roles get no table access and every table has row level security on.

Supabase grants anon/authenticated SELECT on new public tables by default and serves them over
PostgREST to anyone holding the project's publishable key; its linter flags this as
rls_disabled_in_public (ERROR). The owner role bypasses RLS, so the API is unaffected. On plain
Postgres (local, tests) the roles do not exist and only RLS is switched on.

Revision ID: 0025
Revises: 0024
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

SCHEMAS = ("public", "analytics")


def upgrade() -> None:
    op.execute(f"""
    DO $$
    DECLARE r record;
    BEGIN
      FOR r IN SELECT schemaname, tablename FROM pg_tables
               WHERE schemaname IN ({", ".join(f"'{s}'" for s in SCHEMAS)}) LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', r.schemaname, r.tablename);
      END LOOP;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
         AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
        REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM anon, authenticated;
        -- Tables the migrations create from now on (as the current role) stay closed too.
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                       'REVOKE ALL ON TABLES FROM anon, authenticated', current_user);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                       'REVOKE ALL ON SEQUENCES FROM anon, authenticated', current_user);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                       'REVOKE ALL ON FUNCTIONS FROM anon, authenticated', current_user);
      END IF;
    END $$;
    """)


def downgrade() -> None:
    # Re-opening the Data API is a deliberate, manual decision; only RLS is switched back off.
    op.execute(f"""
    DO $$
    DECLARE r record;
    BEGIN
      FOR r IN SELECT schemaname, tablename FROM pg_tables
               WHERE schemaname IN ({", ".join(f"'{s}'" for s in SCHEMAS)}) LOOP
        EXECUTE format('ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY', r.schemaname, r.tablename);
      END LOOP;
    END $$;
    """)
