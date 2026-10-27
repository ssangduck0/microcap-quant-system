#!/usr/bin/env bash
# Daily SQLite backup (consistent copy while services run), gzip, keep 14 days.
# + 서버 밖 사본(2026-10-28): .env 에 R2_ACCOUNT_ID·R2_ACCESS_KEY_ID·R2_SECRET_ACCESS_KEY·R2_BUCKET 이 있으면
#   같은 파일을 Cloudflare R2(S3 호환, 10GB 무료)에도 올리고, R2 쪽은 R2_KEEP_DAYS(기본 21일)만 보관한다.
#   서버 디스크가 통째로 죽어도 R2 에 최근 3주치 DB 가 남는다. 값이 없으면 예전처럼 서버 안 백업만 한다.
set -euo pipefail
DATA_DIR=${DATA_DIR:-/home/quant/data}
BACKUP_DIR=${BACKUP_DIR:-/home/quant/backup}
ENV_FILE=${ENV_FILE:-/home/quant/quant_system/.env}
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"   # 어디서 실행하든(sudo 로 손 실행 포함) find 가 시작 디렉터리 때문에 실패하지 않게
f="$BACKUP_DIR/quant-$(date +%Y%m%d).db"
sqlite3 "$DATA_DIR/quant.db" ".backup '$f'"
gzip -f "$f"
find "$BACKUP_DIR" -name 'quant-*.db.gz' -mtime +14 -delete
echo "backup ok: $f.gz"

# ---- Cloudflare R2 복사(선택) — 설정은 환경변수로만, rclone 설정 파일 없음
r2_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r"' | sed "s/^'//; s/'$//"; }
R2_ACCOUNT_ID=$(r2_env R2_ACCOUNT_ID); R2_ACCESS_KEY_ID=$(r2_env R2_ACCESS_KEY_ID)
R2_SECRET_ACCESS_KEY=$(r2_env R2_SECRET_ACCESS_KEY); R2_BUCKET=$(r2_env R2_BUCKET)
R2_KEEP_DAYS=$(r2_env R2_KEEP_DAYS); R2_KEEP_DAYS=${R2_KEEP_DAYS:-21}
if [ -n "$R2_ACCOUNT_ID" ] && [ -n "$R2_ACCESS_KEY_ID" ] && [ -n "$R2_SECRET_ACCESS_KEY" ] && [ -n "$R2_BUCKET" ] && command -v rclone >/dev/null 2>&1; then
  # NO_HEAD: 업로드 뒤 rclone(1.60) 이 보내는 확인용 HEAD 요청을 R2 가 501 로 거부해 '실패→재시도 통과'로 찍히던 것(첫 시험 10/28) → HEAD 를 끄고 아래 rclone check 로 크기 대조
  export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true RCLONE_CONFIG_R2_NO_HEAD=true
  export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
  export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
  if rclone copyto "$f.gz" "r2:${R2_BUCKET}/$(basename "$f").gz" --s3-upload-cutoff 100M --s3-chunk-size 50M --retries 3 --low-level-retries 10 -q; then
    if rclone check "$BACKUP_DIR" "r2:${R2_BUCKET}" --include "$(basename "$f").gz" --size-only -q 2>/dev/null; then
      echo "r2 ok: ${R2_BUCKET}/$(basename "$f").gz 크기 일치 (R2 보관 ${R2_KEEP_DAYS}일)"
    else
      echo "r2 WARNING: 올라갔지만 크기 대조 실패 — $(basename "$f").gz" >&2
    fi
    rclone delete "r2:${R2_BUCKET}" --include 'quant-*.db.gz' --min-age "${R2_KEEP_DAYS}d" -q || true
  else
    echo "r2 upload FAILED" >&2
  fi
else
  echo "r2 skipped (R2_* 미설정 또는 rclone 없음)"
fi
