#!/usr/bin/env bash
# Dump SQLite DB (safe — uses the sqlite3 .backup CLI, works while server runs).
# Rotates: keeps last 30 dumps.
set -euo pipefail

DB_PATH="${DB_PATH:-/opt/golf/data/golf.db}"
OUT_DIR="${OUT_DIR:-/opt/golf/backups}"
RETAIN="${RETAIN:-30}"

mkdir -p "$OUT_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$OUT_DIR/golf-$STAMP.db"

sqlite3 "$DB_PATH" ".backup '$OUT'"
gzip -9 "$OUT"
echo "[$(date -Iseconds)] backup → $OUT.gz ($(du -h "$OUT.gz" | cut -f1))"

# Rotate
ls -1t "$OUT_DIR"/golf-*.db.gz 2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm --
