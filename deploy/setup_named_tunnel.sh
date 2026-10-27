#!/usr/bin/env bash
# Fixed addresses with a Cloudflare named tunnel (run as root on the server, once).
#   bash deploy/setup_named_tunnel.sh example.com
# Result: https://dash.example.com -> owner dashboard (8501), https://guest.example.com -> guest dashboard (8502)
# Needs: the domain is in your Cloudflare account (bought at Cloudflare Registrar, or nameservers pointed to Cloudflare).
set -euo pipefail
DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then echo "usage: bash deploy/setup_named_tunnel.sh yourdomain.com"; exit 1; fi
APP_USER=quant
APP_DIR=/home/$APP_USER/quant_system
ENV="$APP_DIR/.env"
CF="sudo -u $APP_USER -H cloudflared"

if [ ! -f /home/$APP_USER/.cloudflared/cert.pem ]; then
  echo "== 1/4 Cloudflare login: open the URL below in your PC browser, sign in, and pick $DOMAIN"
  $CF tunnel login
fi

echo "== 2/4 tunnels"
for T in quant-dash quant-guest; do
  if $CF tunnel list 2>/dev/null | awk '{print $2}' | grep -qx "$T"; then echo "exists: $T"; else $CF tunnel create "$T"; fi
done

echo "== 3/4 DNS names"
$CF tunnel route dns --overwrite-dns quant-dash "dash.$DOMAIN"
$CF tunnel route dns --overwrite-dns quant-guest "guest.$DOMAIN"

echo "== 4/4 .env + restart"
touch "$ENV"
sed -i 's/\r$//' "$ENV"                                   # Windows 줄끝(CRLF) 정리
sed -i 's/\(.\)DASH_TUNNEL_NAME=/\1\nDASH_TUNNEL_NAME=/' "$ENV"   # 예전에 줄바꿈 없이 붙은 줄 떼기
sed -i '/^DASH_TUNNEL_NAME=/d;/^DASH_PUBLIC_URL=/d;/^GUEST_TUNNEL_NAME=/d;/^GUEST_PUBLIC_URL=/d' "$ENV"
[ -s "$ENV" ] && [ -n "$(tail -c1 "$ENV")" ] && echo >> "$ENV"   # 마지막 줄에 줄바꿈이 없으면 먼저 넣고 붙임
cat >> "$ENV" <<EOF
DASH_TUNNEL_NAME=quant-dash
DASH_PUBLIC_URL=https://dash.$DOMAIN
GUEST_TUNNEL_NAME=quant-guest
GUEST_PUBLIC_URL=https://guest.$DOMAIN
EOF
chown $APP_USER:$APP_USER "$ENV"
chmod 600 "$ENV"
systemctl restart quant-tunnel quant-guest-tunnel
sleep 15
echo
echo "Done. Open:  https://dash.$DOMAIN   (guest: https://guest.$DOMAIN)"
echo "Logs:  journalctl -u quant-tunnel -n 20 --no-pager"
