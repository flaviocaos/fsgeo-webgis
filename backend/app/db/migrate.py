"""Aplica as migrações SQL em ordem, registrando as já aplicadas.

Uso: python -m app.db.migrate
"""
from pathlib import Path

import psycopg

from app.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def migrate(database_url: str | None = None) -> list[str]:
    url = database_url or get_settings().database_url
    applied_now: list[str] = []
    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        # Trava para impedir duas réplicas migrando ao mesmo tempo.
        conn.execute("SELECT pg_advisory_xact_lock(7300112)")
        done = {r[0] for r in conn.execute("SELECT name FROM public.schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO public.schema_migrations(name) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
        conn.commit()
    return applied_now


if __name__ == "__main__":
    names = migrate()
    print("Migrações aplicadas:", ", ".join(names) if names else "nenhuma (banco já atualizado)")
