import sys

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from hellomyme.config import get_settings


def describe(url: str) -> str:
    """Connection target for deploy logs, never the password itself."""
    u = make_url(url)
    pw = u.password or ""
    suspicious = [c for c in "@#/:?%[] " if c in pw]
    return (f"driver={u.drivername} user={u.username} host={u.host} port={u.port} "
            f"db={u.database} query={dict(u.query)} password_length={len(pw)}"
            + (f" password_has_special_chars={suspicious}" if suspicious else ""))


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url
    print(f"[migrations] connecting: {describe(url)}", file=sys.stderr, flush=True)
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline mode is not supported; migrations contain raw SQL")
run_migrations_online()
