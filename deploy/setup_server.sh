#!/usr/bin/env bash
# Quant dashboard server setup for Ubuntu 22.04/24.04 (run as root, once).
#   sudo bash deploy/setup_server.sh
# It mirrors the 6 Windows windows + morning update task as systemd services:
#   quant-scanner, quant-dashboard(8501), quant-guest(8502), quant-tunnel, quant-guest-tunnel, quant-collector
#   quant-cases.timer (Tue-Sat 07:30 Asia/Seoul) and quant-backup.timer (daily 03:00 Asia/Seoul, keep 14 days)
# Code:  /home/quant/quant_system      DB: /home/quant/data/quant.db      Backups: /home/quant/backup
set -euo pipefail

APP_USER=quant
HOME_DIR=/home/$APP_USER
APP_DIR=$HOME_DIR/quant_system
DATA_DIR=$HOME_DIR/data
BACKUP_DIR=$HOME_DIR/backup
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1/7 packages"
export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o DPkg::Lock::Timeout=900"   # wait (up to 15 min) if automatic updates hold the dpkg lock
$APT update -y
$APT install -y python3 python3-venv python3-pip sqlite3 curl ca-certificates tzdata gzip
timedatectl set-timezone Asia/Seoul || true

echo "== DNS: use Cloudflare resolvers first (Vultr resolvers can cache 'not found' for new names for ~30 min)"
if [ -f /etc/resolv.conf ] && [ ! -L /etc/resolv.conf ] && ! grep -q "^nameserver 1.1.1.1" /etc/resolv.conf; then
  sed -i '1i nameserver 1.0.0.1' /etc/resolv.conf
  sed -i '1i nameserver 1.1.1.1' /etc/resolv.conf
fi

echo "== 2/7 user and folders"
id -u $APP_USER >/dev/null 2>&1 || useradd -m -s /bin/bash $APP_USER
mkdir -p "$APP_DIR" "$DATA_DIR" "$BACKUP_DIR"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  cp -a "$SRC_DIR"/. "$APP_DIR"/
fi
chown -R $APP_USER:$APP_USER "$HOME_DIR"

echo "== 3/7 python venv"
sudo -u $APP_USER python3 -m venv "$APP_DIR/venv"
sudo -u $APP_USER "$APP_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u $APP_USER "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "== firewall: only SSH in (dashboards listen on 127.0.0.1, phone access goes out through Cloudflare tunnel)"
$APT install -y ufw
ufw allow OpenSSH
ufw --force enable

echo "== security: fail2ban (ban IPs after repeated SSH login failures) + automatic security updates"
$APT install -y fail2ban unattended-upgrades
systemctl enable --now fail2ban
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'AUEOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
AUEOF
systemctl enable --now unattended-upgrades || true

echo "== 4/7 cloudflared"
if ! command -v cloudflared >/dev/null 2>&1; then
  ARCH=$(dpkg --print-architecture)
  curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  $APT install -y /tmp/cloudflared.deb
fi

echo "== 5/7 .env check"
if [ ! -f "$APP_DIR/.env" ]; then
  echo "!! $APP_DIR/.env not found. Copy your Windows .env there (DASH_PASSWORD, TELEGRAM_*, SEC_USER_AGENT, ANTHROPIC_API_KEY, TOSS_*)."
fi

echo "== 6/7 systemd services"
PY="$APP_DIR/venv/bin/python"
THEME='--theme.base dark --theme.primaryColor #E5484D --theme.backgroundColor #101318 --theme.secondaryBackgroundColor #191D24 --theme.textColor #E6E8EB'
unit() {  # name, description, command, extra env
  cat > /etc/systemd/system/$1.service <<EOF
[Unit]
Description=$2
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUTF8=1
Environment=PYTHONIOENCODING=utf-8
Environment=QUANT_DB=$DATA_DIR/quant.db
$4
ExecStart=$3
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
}
unit quant-scanner "Quant scanner" "$PY scanner.py" ""
unit quant-dashboard "Quant dashboard (owner, 8501)" "$PY -m streamlit run dashboard.py --server.headless true --server.address 127.0.0.1 --server.port 8501 $THEME" ""
unit quant-guest "Quant guest dashboard (8502)" "$PY -m streamlit run dashboard.py --server.headless true --server.address 127.0.0.1 --server.port 8502 --client.showErrorDetails false $THEME" "Environment=QUANT_GUEST_ONLY=1"
unit quant-tunnel "Quant phone tunnel" "$PY tunnel.py" "Environment=DASH_PORT=8501"
unit quant-guest-tunnel "Quant guest tunnel" "$PY tunnel.py" "Environment=DASH_PORT=8502
Environment=TUNNEL_KIND=guest"
unit quant-collector "Quant event collector" "$PY eventlab.py run" ""

cat > /etc/systemd/system/quant-cases.service <<EOF
[Unit]
Description=Quant morning update (cases.py update)
[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUTF8=1
Environment=QUANT_DB=$DATA_DIR/quant.db
ExecStart=$PY cases.py update
TimeoutStartSec=4h
EOF
cat > /etc/systemd/system/quant-cases.timer <<EOF
[Unit]
Description=Quant morning update Tue-Sat 07:30 KST
[Timer]
OnCalendar=Tue..Sat *-*-* 07:30:00 Asia/Seoul
Persistent=true
[Install]
WantedBy=timers.target
EOF
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
cat > /etc/systemd/system/quant-backup.service <<EOF
[Unit]
Description=Quant DB backup (keep 14 days)
[Service]
Type=oneshot
User=$APP_USER
Environment=DATA_DIR=$DATA_DIR
Environment=BACKUP_DIR=$BACKUP_DIR
ExecStart=/bin/bash $APP_DIR/deploy/backup_db.sh
EOF
cat > /etc/systemd/system/quant-backup.timer <<EOF
[Unit]
Description=Quant DB backup daily 03:00 KST
[Timer]
OnCalendar=*-*-* 03:00:00 Asia/Seoul
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload

echo "== 7/7 done"
cat <<EOF

Next steps (see deploy/README_SERVER.md):
  1) connectivity test:   sudo -u $APP_USER $PY $APP_DIR/deploy/check_connectivity.py
  2) put DB at $DATA_DIR/quant.db (from Windows C:\\quant_data\\quant.db), then: chown $APP_USER:$APP_USER $DATA_DIR/quant.db
  3) start everything:    systemctl enable --now quant-scanner quant-dashboard quant-guest quant-tunnel quant-guest-tunnel quant-collector quant-cases.timer quant-backup.timer quant-chartex.timer quant-warm.timer
  4) status / logs:       systemctl status 'quant-*'    journalctl -u quant-scanner -f
EOF
