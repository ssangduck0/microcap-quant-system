#!/usr/bin/env bash
# 기존 서버에 📡 ChartExchange 아침 타이머(화~토 06:40 KST) 추가. root 로: bash /home/quant/quant_system/deploy/install_chartex_timer.sh
set -euo pipefail
APP_USER=quant; APP_DIR=/home/quant/quant_system; DATA_DIR=/home/quant/data; PY=$APP_DIR/venv/bin/python
cat > /etc/systemd/system/quant-chartex.service <<EOF
[Unit]
Description=Quant ChartExchange short data (chartex.py collect)
[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUTF8=1
Environment=QUANT_DB=$DATA_DIR/quant.db
ExecStart=$PY chartex.py collect
TimeoutStartSec=2h
EOF
cat > /etc/systemd/system/quant-chartex.timer <<EOF
[Unit]
Description=Quant ChartExchange short data Tue-Sat 06:40 KST
[Timer]
OnCalendar=Tue..Sat *-*-* 06:40:00 Asia/Seoul
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now quant-chartex.timer
systemctl list-timers 'quant-*' --no-pager
