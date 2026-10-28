#!/bin/bash
# 전체 테스트 실행(어느 폴더·어느 PC 에서나 — 테스트가 자기 위치에서 프로젝트 폴더를 찾음).
# 한 번에 5분 제한이 있어 4~5번에 나눠 돌린다: bash tests/run_all.sh 1 (2,3,4,5)
cd "$(dirname "$0")"
export DASH_PASSWORD= PYTHONUTF8=1 PYTHONIOENCODING=utf-8 QUANT_OFFLINE=1   # QUANT_OFFLINE: 인터넷·Claude 호출 차단(config 오프라인 모드, 임시 DB 면 자동) · .env 의 비밀번호가 있으면 화면이 비밀번호 창에서 멈춰 모든 화면 테스트가 실패 · 한글 파일 읽기
TMPD=$(python -c "import tempfile; print(tempfile.gettempdir())")
cp apps/*_app.py "$TMPD"/ 2>/dev/null
ALL=$(ls test_*.py | sort)
N=$(echo "$ALL" | wc -l); PART=${1:-1}; SIZE=$(( (N + 4) / 5 ))
for t in $(echo "$ALL" | sed -n "$(( (PART-1)*SIZE+1 )),$(( PART*SIZE ))p"); do
  r=$(timeout 100 python "$t" 2>&1 | grep -E "ALL OK|UI OK|REPORT OK|CHART OK|Error:|assert|Traceback" | grep -v "조회 실패\|전환\|DNSError\|ALL OK 2" | tail -1)
  case "$r" in *"OK"*) ;; *) echo "$t: $r";; esac
done
echo "--- part $PART done ($SIZE files)"
