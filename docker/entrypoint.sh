#!/usr/bin/env bash
# Container entrypoint: wait for Postgres, run migrations (schema + seed), then
# launch the requested process. `docker compose up` always lands on a fully
# migrated, seeded database — no manual steps on the server.
set -euo pipefail

wait_for_db() {
  echo "⏳ Waiting for database at ${POSTGRES_HOST}:${POSTGRES_PORT}…"
  python - <<'PY'
import time, sys
import psycopg
from app.config import get_settings
s = get_settings()
dsn = f"host={s.postgres_host} port={s.postgres_port} dbname={s.postgres_db} user={s.postgres_user} password={s.postgres_password}"
for attempt in range(60):
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            print("✅ Database is ready.")
            sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        time.sleep(2)
print("❌ Database not reachable in time", file=sys.stderr)
sys.exit(1)
PY
}

run_migrations() {
  echo "🚀 Running Alembic migrations (schema + seed)…"
  alembic upgrade head
}

case "${1:-bot}" in
  bot)
    wait_for_db
    run_migrations
    echo "🤖 Starting bot…"
    exec python -m app.bot.main
    ;;
  migrate)
    wait_for_db
    run_migrations
    ;;
  ingest)
    shift
    exec python -m app.ingestion.ingest "$@"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
