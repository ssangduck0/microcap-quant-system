#!/usr/bin/env bash
# 기존 서버에 🔥 화면 캐시 데우기 타이머(10분마다 `pagecache.py warm`) 추가. root 로: bash /home/quant/quant_system/deploy/install_warm_timer.sh
# 느린 화면(🏁 종합 순위 · 🎯 장마감 체크리스트 · ⚡ EFFECT · 📚 과거 사례)의 계산을 미리 해 두어 화면이 바로 뜨게 한다. 없어도 화면은 예전처럼(느리게) 동작.
set -euo pipefail
APP_USER=quant; APP_DIR=/home/quant/quant_system; DATA_DIR=/home/quant/data; PY=$APP_DIR/venv/bin/python
cat > /etc/systemd/system/quant-warm.service <<EOF
[Unit]
Description=Quant page cache warm (pagecache.py warm)
[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUTF8=1
Environment=QUANT_DB=$DATA_DIR/quant.db
ExecStart=$PY pagecache.py warm
Nice=10
TimeoutStartSec=20min
EOF
cat > /etc/systemd/system/quant-warm.timer <<EOF
[Unit]
Description=Quant page cache warm every 10 min
[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
AccuracySec=30s
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now quant-warm.timer
systemctl start --no-block quant-warm.service
systemctl list-timers 'quant-*' --no-pager
