#!/usr/bin/env bash
# Turn off SSH password login (key-only). Run ONLY after your SSH key login works.
#   bash deploy/harden_ssh.sh
# Safety: refuses to run if root has no authorized SSH key. Keep your current SSH window open
# and test a new login in a second window before closing it.
set -euo pipefail
AK=/root/.ssh/authorized_keys
if [ ! -s "$AK" ] || ! grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2)' "$AK"; then
  echo "!! No SSH key found in $AK. Add your public key first (see README_SERVER.md step 1-3). Nothing changed."
  exit 1
fi
# sshd uses the FIRST value it reads; files in sshd_config.d are read in name order,
# so this must sort before cloud-init's 50-cloud-init.conf (which may say PasswordAuthentication yes).
cat > /etc/ssh/sshd_config.d/00-quant-hardening.conf <<'CFEOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CFEOF
sshd -t
systemctl restart ssh || systemctl restart sshd
echo "OK: password login is off. Open a NEW window and test:  ssh root@<server-ip>"
echo "If it fails, use the Vultr web console (View Console) and delete /etc/ssh/sshd_config.d/00-quant-hardening.conf"
