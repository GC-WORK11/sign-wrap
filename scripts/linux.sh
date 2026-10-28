#!/usr/bin/env bash
# Sign-Flow setup and launcher for Linux (X11 session).
#
#   scripts/linux.sh            check tools, npm install, start the daemon
#   scripts/linux.sh setup      check tools and npm install only
#   scripts/linux.sh check      check tools only (no changes)
#   scripts/linux.sh <command>  pass a command to the wrap CLI:
#                               start stop restart status pair logs doctor
#                               send bridge tunnel open install
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAP="$ROOT/bin/wrap"

have() { command -v "$1" >/dev/null 2>&1; }

check() {
    local missing=() warn=0
    for t in node npm python3 curl xdotool xprop xclip wmctrl convert; do
        have "$t" || missing+=("$t")
    done
    python3 -c 'import Xlib' >/dev/null 2>&1 || missing+=("python3-xlib")
    if [ ${#missing[@]} -gt 0 ]; then
        echo "missing: ${missing[*]}"
        echo "Debian/Ubuntu: sudo apt install -y nodejs npm python3 curl xdotool x11-utils xclip wmctrl imagemagick python3-xlib"
        echo "Fedora:        sudo dnf install -y nodejs npm python3 curl xdotool xprop xclip wmctrl ImageMagick python3-xlib"
        echo "Arch:          sudo pacman -S --needed nodejs npm python curl xdotool xorg-xprop xclip wmctrl imagemagick python-xlib"
        return 1
    fi
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)'; then :; else
        echo "python 3.7 or newer is required"; return 1
    fi
    case "${XDG_SESSION_TYPE:-}" in
        wayland) echo "warning: Wayland session. Typing and window control need X11 (pick an Xorg session at login)."; warn=1 ;;
        "") [ -z "${DISPLAY:-}" ] && { echo "warning: no desktop session found (DISPLAY is unset)."; warn=1; } ;;
    esac
    for t in pactl playerctl brightnessctl nmcli notify-send adb cloudflared; do
        have "$t" || echo "optional, not found: $t"
    done
    [ $warn -eq 0 ] && echo "tools: ok"
    return 0
}

setup() {
    check
    (cd "$ROOT" && npm install --no-audit --no-fund)
    echo "setup done. Optional: run 'npm link' in $ROOT to put 'wrap' on your PATH."
}

cmd="${1:-}"
case "$cmd" in
    "")       setup; exec "$WRAP" start ;;
    setup)    setup ;;
    check)    check ;;
    start|stop|restart|status|pair|logs|doctor|send|bridge|tunnel|open|install)
              exec "$WRAP" "$@" ;;
    -h|--help|help)
              awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0" ;;
    *)        echo "unknown command: $cmd (try: $0 help)"; exit 2 ;;
esac
