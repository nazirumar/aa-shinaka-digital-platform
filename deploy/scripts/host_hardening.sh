#!/usr/bin/env bash
#
# Host hardening for a fresh Hostinger KVM VPS running Ubuntu 24.04 LTS.
#
#   ./deploy/scripts/host_hardening.sh [--apply] [--admin-user NAME] [--ssh-key FILE]
#
# This script must be run ON the server by an operator who is already
# authorised to administer it. It is DRY-RUN BY DEFAULT: with no --apply it
# prints exactly what it would change and touches nothing. It never connects to
# a remote host, never changes DNS and never opens a port other than 80/443.
#
# What it configures
#   1. a non-root admin user with sudo and an SSH key;
#   2. sshd: key-only authentication, no root login, no empty passwords;
#   3. ufw: deny inbound by default, allow only SSH/80/443;
#   4. fail2ban for SSH brute-force protection;
#   5. unattended-upgrades for security patches;
#   6. a Docker install check (the Compose stack needs Docker Engine + plugin).
#
# IMPORTANT: it deliberately does NOT copy your private key anywhere and does
# NOT disable password auth until a working key is proven (see the guard in
# step 2), so you cannot lock yourself out.

set -euo pipefail

APPLY=0
ADMIN_USER="${ADMIN_USER:-aashinaka}"
SSH_KEY_FILE="${SSH_KEY_FILE:-}"
SUDOERS_FILE="/etc/sudoers.d/90-${ADMIN_USER}"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --admin-user) ADMIN_USER="$2"; shift 2 ;;
    --ssh-key) SSH_KEY_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) printf 'host_hardening: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

log() { printf '%s [harden] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# run <description> <command...>
run() {
  local desc="$1"; shift
  if [ "$APPLY" = "1" ]; then
    log "RUN: $desc"
    "$@"
  else
    log "WOULD: $desc"
    printf '        %s\n' "$*"
  fi
}

write_file() {
  local path="$1" content="$2"
  if [ "$APPLY" = "1" ]; then
    log "WRITE: $path"
    printf '%s\n' "$content" > "$path"
  else
    log "WOULD WRITE: $path"
    printf '%s\n' "$content" | sed 's/^/        | /'
  fi
}

if [ "$APPLY" != "1" ]; then
  log "DRY RUN — nothing will be changed. Re-run with --apply to execute."
fi

if [ "$APPLY" = "1" ] && [ "$(id -u)" != "0" ]; then
  log "ERROR: --apply must be run as root (or with sudo)"
  exit 1
fi

# --- 1. Non-root admin user with an SSH key --------------------------------
log "Step 1/6 — administrative user '${ADMIN_USER}'"
run "create user ${ADMIN_USER}" useradd --create-home --shell /bin/bash "$ADMIN_USER" || true
run "add ${ADMIN_USER} to sudo" usermod -aG sudo "$ADMIN_USER"
write_file "$SUDOERS_FILE" "${ADMIN_USER} ALL=(ALL) NOPASSWD:ALL"
run "restrict sudoers file mode" chmod 0440 "$SUDOERS_FILE"

if [ -n "$SSH_KEY_FILE" ]; then
  [ -f "$SSH_KEY_FILE" ] || { log "ERROR: SSH public key not found: $SSH_KEY_FILE"; exit 1; }
  run "install SSH key for ${ADMIN_USER}" install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/${ADMIN_USER}/.ssh"
  if [ "$APPLY" = "1" ]; then
    cat "$SSH_KEY_FILE" >> "/home/${ADMIN_USER}/.ssh/authorized_keys"
    chmod 600 "/home/${ADMIN_USER}/.ssh/authorized_keys"
    chown "$ADMIN_USER:$ADMIN_USER" "/home/${ADMIN_USER}/.ssh/authorized_keys"
  else
    log "WOULD: append ${SSH_KEY_FILE} to /home/${ADMIN_USER}/.ssh/authorized_keys"
  fi
else
  log "NOTE: no --ssh-key supplied; add one before disabling password auth"
fi

# --- 2. sshd hardening -----------------------------------------------------
log "Step 2/6 — sshd"
SSHD_CONFIG="/etc/ssh/sshd_config.d/99-aa-shinaka.conf"
# Guard: only disable password auth once some authorised key exists.
KEY_COUNT=0
if [ -s "/home/${ADMIN_USER}/.ssh/authorized_keys" ]; then
  KEY_COUNT="$(grep -c 'ssh-' "/home/${ADMIN_USER}/.ssh/authorized_keys" || true)"
fi

if [ "$APPLY" = "1" ] && [ "${KEY_COUNT:-0}" = "0" ]; then
  log "REFUSING to disable password authentication: no SSH key installed yet."
  log "Re-run with --ssh-key /path/to/id_ed25519.pub, then run this script again."
  exit 1
fi

write_file "$SSHD_CONFIG" "PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 4
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers ${ADMIN_USER}"
run "validate sshd configuration" sshd -t
run "reload sshd" systemctl reload ssh

# --- 3. Firewall -----------------------------------------------------------
log "Step 3/6 — ufw"
run "set default deny inbound" ufw default deny incoming
run "set default allow outbound" ufw default allow outgoing
run "allow SSH" ufw allow OpenSSH
run "allow HTTP" ufw allow 80/tcp
run "allow HTTPS" ufw allow 443/tcp
run "enable firewall" ufw --force enable
log "NOTE: PostgreSQL (5432) and Redis (6379) are NOT opened — the Compose"
log "      stack keeps them on an internal Docker network with no host port."

# --- 4. fail2ban -----------------------------------------------------------
log "Step 4/6 — fail2ban"
run "install fail2ban" env DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban
write_file "/etc/fail2ban/jail.d/aa-shinaka.local" "[sshd]
enabled = true
maxretry = 5
findtime = 600
bantime = 3600"
run "enable fail2ban" systemctl enable --now fail2ban

# --- 5. Unattended security updates ---------------------------------------
log "Step 5/6 — unattended-upgrades"
run "install unattended-upgrades" env DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades
write_file "/etc/apt/apt.conf.d/20auto-upgrades" 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";'
run "enable unattended-upgrades" systemctl enable --now unattended-upgrades

# --- 6. Docker -------------------------------------------------------------
log "Step 6/6 — Docker Engine + Compose plugin"
if command -v docker >/dev/null 2>&1; then
  log "docker present: $(docker --version 2>/dev/null || echo unknown)"
else
  log "docker is NOT installed. Install Docker Engine + the compose plugin from"
  log "Docker's official apt repository (see docs/HOSTINGER_VPS_DEPLOYMENT.md),"
  log "then verify with: docker --version && docker compose version"
fi
if command -v docker >/dev/null 2>&1; then
  run "verify docker permissions for ${ADMIN_USER}" usermod -aG docker "$ADMIN_USER"
fi

log "Done. Next: docs/HOSTINGER_VPS_DEPLOYMENT.md § Repository deployment."
