#!/usr/bin/env bash
#
# Chirpa — Linux installer
#
# Installs Chirpa for the current user into a self-contained directory, stages
# the chart asset, and (optionally) sets up a systemd user service so the
# dashboard starts on login and restarts on failure.
#
# Usage:
#   ./install.sh                 # install + set up the systemd service
#   ./install.sh --no-service    # install only, don't touch systemd
#   ./install.sh --dir DIR       # install to DIR (default: ~/.local/share/chirpa)
#   ./install.sh --port N        # serve on port N (default: 8090)
#   ./install.sh --uninstall     # remove the service and installed files
#
# Nothing is installed system-wide and no root/sudo is required. Your data
# (cameras, images, species DB) lives in ~/.chirpa and is never touched by
# install or uninstall.

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────
INSTALL_DIR="${CHIRPA_INSTALL_DIR:-$HOME/.local/share/chirpa}"
PORT="${CHIRPA_PORT:-8090}"
SERVICE=1
UNINSTALL=0
SERVICE_NAME="chirpa"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/$SERVICE_NAME.service"

# Repo root = parent of this script's directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

c_info()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
c_ok()    { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
c_warn()  { printf '\033[33m  !\033[0m %s\n' "$*"; }
c_err()   { printf '\033[31merror:\033[0m %s\n' "$*" >&2; }

# ── Parse args ───────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --no-service) SERVICE=0 ;;
    --service)    SERVICE=1 ;;
    --uninstall)  UNINSTALL=1 ;;
    --dir)        INSTALL_DIR="$2"; shift ;;
    --port)       PORT="$2"; shift ;;
    -h|--help)    tail -n +2 "$0" | grep '^#' | sed 's/^#\{1,\} \{0,1\}//'; exit 0 ;;
    *) c_err "unknown option: $1"; exit 2 ;;
  esac
  shift
done

have_systemd() { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }

# ── Uninstall ────────────────────────────────────────────────────────
if [ "$UNINSTALL" = 1 ]; then
  c_info "Uninstalling Chirpa"
  if have_systemd && [ -f "$UNIT_FILE" ]; then
    systemctl --user disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl --user daemon-reload 2>/dev/null || true
    c_ok "removed systemd service"
  fi
  if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    c_ok "removed $INSTALL_DIR"
  fi
  c_info "Your data in ~/.chirpa was left untouched. Delete it manually to fully remove everything."
  exit 0
fi

# ── Prerequisite checks ──────────────────────────────────────────────
c_info "Checking prerequisites"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  c_err "python3 is required but was not found."
  echo "  Install it with your package manager, e.g.:"
  echo "    Debian/Ubuntu : sudo apt install python3"
  echo "    Fedora        : sudo dnf install python3"
  echo "    Arch          : sudo pacman -S python"
  exit 1
fi
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
c_ok "python3 found ($PYVER) at $PY"

if command -v ffprobe >/dev/null 2>&1; then
  c_ok "ffprobe found — RTSP stream verification enabled"
else
  c_warn "ffprobe not found — the camera wizard still works (host + port check),"
  echo "      but won't verify the RTSP handshake. To enable it install ffmpeg:"
  echo "        Debian/Ubuntu : sudo apt install ffmpeg"
  echo "        Fedora        : sudo dnf install ffmpeg"
  echo "        Arch          : sudo pacman -S ffmpeg"
fi

# ── Copy files ───────────────────────────────────────────────────────
c_info "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
install -m 0644 "$REPO_ROOT/birdnet_gui.py" "$INSTALL_DIR/birdnet_gui.py"
install -m 0644 "$REPO_ROOT/chart.min.js"   "$INSTALL_DIR/chart.min.js"
c_ok "copied birdnet_gui.py and chart.min.js"

# ── systemd user service ─────────────────────────────────────────────
if [ "$SERVICE" = 1 ]; then
  if have_systemd; then
    c_info "Setting up systemd user service ($SERVICE_NAME)"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Chirpa BirdNET Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$PY $INSTALL_DIR/birdnet_gui.py
WorkingDirectory=$INSTALL_DIR
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=CHIRPA_PORT=$PORT
Environment=CHIRPA_NO_BROWSER=1

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    c_ok "service enabled and started"
    # Let it keep running after logout (best-effort; needs lingering).
    loginctl enable-linger "$USER" >/dev/null 2>&1 || \
      c_warn "could not enable linger — service stops at logout (run: sudo loginctl enable-linger $USER)"
    echo
    c_info "Manage it with:"
    echo "    systemctl --user status $SERVICE_NAME"
    echo "    systemctl --user restart $SERVICE_NAME"
    echo "    journalctl --user -u $SERVICE_NAME -f"
  else
    c_warn "systemd not detected — skipping service setup."
    SERVICE=0
  fi
fi

# ── Done ─────────────────────────────────────────────────────────────
echo
c_ok "Chirpa installed."
echo
if [ "$SERVICE" = 1 ]; then
  echo "  Dashboard: http://127.0.0.1:$PORT"
else
  echo "  Start it with:"
  echo "    CHIRPA_PORT=$PORT $PY \"$INSTALL_DIR/birdnet_gui.py\""
  echo "  Then open: http://127.0.0.1:$PORT"
fi
