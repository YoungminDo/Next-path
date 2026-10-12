from sqlalchemy import text


def test_every_table_has_row_level_security(engine):
    """Migration 0025: nothing is served over the Supabase Data API. A table added later without
    RLS (or without the same revoke) would be readable with the project's publishable key."""
    with engine.connect() as conn:
        open_tables = conn.execute(text(
            """SELECT n.nspname || '.' || c.relname FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE c.relkind IN ('r', 'p') AND n.nspname IN ('public', 'analytics', 'pii')
                 AND NOT c.relrowsecurity ORDER BY 1""")).scalars().all()
    assert open_tables == []
