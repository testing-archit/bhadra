#!/usr/bin/env bash
# Nightly Postgres backup on the production VM (installed in tech_intern's
# crontab, 21:00 UTC = 02:30 IST):
#   0 21 * * * /home/tech_intern/charcha/tools/backup-db.sh >> /home/tech_intern/charcha/backups/backup.log 2>&1
# Keeps KEEP_DAYS of compressed dumps in ~/charcha/backups. Restore with:
#   gunzip -c backups/nightly_<stamp>.sql.gz | docker compose -f docker-compose.prod.yml exec -T postgres psql -U charcha charcha
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p backups
stamp="$(date -u +%Y%m%d_%H%M%S)"
target="backups/nightly_${stamp}.sql.gz"
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U charcha --no-owner charcha | gzip -9 > "${target}.partial"
# A dump that ends early is worse than none: only keep complete ones.
gunzip -c "${target}.partial" | tail -n 5 | grep -q "PostgreSQL database dump complete"
mv "${target}.partial" "${target}"
find backups -name 'nightly_*.sql.gz' -mtime "+${KEEP_DAYS}" -delete
echo "$(date -u +%FT%TZ) backup ok: ${target} ($(du -h "${target}" | cut -f1))"
