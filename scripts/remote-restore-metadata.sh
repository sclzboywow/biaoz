#!/bin/bash
set -euo pipefail
export PGPASSWORD='biaoz'
LOG=/tmp/biaoz-restore.log
SRC="${1:-/tmp/biaoz-metadata.sql}"
: > "$LOG"
echo "restore_start $(date -Is) source=$SRC" | tee -a "$LOG"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS biaoz WITH (FORCE);"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE biaoz OWNER biaoz;"
sed -e '/^SET transaction_timeout/d' -e '/^\\restrict /d' -e '/^\\unrestrict /d' "$SRC" | psql -h localhost -U biaoz -d biaoz -v ON_ERROR_STOP=1 >> "$LOG" 2>&1
echo "restore_end $(date -Is)" | tee -a "$LOG"
psql -h localhost -U biaoz -d biaoz -Atc "SELECT 'standard_resources='||count(*) FROM standard_resources;" | tee -a "$LOG"
psql -h localhost -U biaoz -d biaoz -Atc "SELECT 'document_versions='||count(*) FROM document_versions;" | tee -a "$LOG"
psql -h localhost -U biaoz -d biaoz -Atc "SELECT 'url_sources='||count(*) FROM url_sources;" | tee -a "$LOG"
echo done
