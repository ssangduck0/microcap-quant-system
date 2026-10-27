#!/usr/bin/env bash
# Daily SQLite backup (consistent copy while services run), gzip, keep 14 days.
set -euo pipefail
DATA_DIR=${DATA_DIR:-/home/quant/data}
BACKUP_DIR=${BACKUP_DIR:-/home/quant/backup}
mkdir -p "$BACKUP_DIR"
f="$BACKUP_DIR/quant-$(date +%Y%m%d).db"
sqlite3 "$DATA_DIR/quant.db" ".backup '$f'"
gzip -f "$f"
find "$BACKUP_DIR" -name 'quant-*.db.gz' -mtime +14 -delete
echo "backup ok: $f.gz"
