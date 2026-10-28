#!/usr/bin/env bash
# Sign-Flow setup and launcher for macOS.
#
#   scripts/macos.sh            check tools, npm install, start the daemon
#   scripts/macos.sh setup      check tools and npm install only
#   scripts/macos.sh check      check tools and permissions only (no changes)
#   scripts/macos.sh <command>  pass a command to the wrap CLI:
#                               start stop restart status pair logs doctor
#                               send bridge tunnel open install
#
# Typing and window focus go through System Events, so the terminal app
# you run this from needs Accessibility permission:
#   System Settings > Privacy & Security > Accessibility
# The screenshot action also needs Screen Recording for the same app.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAP="$ROOT/bin/wrap"

have() { command -v "$1" >/dev/null 2>&1; }

check() {
    local missing=()
    [ "$(uname)" = "Darwin" ] || { echo "this script is for macOS; use scripts/linux.sh or scripts/windows.sh"; return 1; }
    for t in node npm python3 curl osascript pbcopy sips; do
        have "$t" || missing+=("$t")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "missing: ${missing[*]}"
        echo "install with Homebrew: brew install node python"
        echo "python3 also comes with the Xcode command line tools: xcode-select --install"
        return 1
    fi
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)'; then :; else
        echo "python 3.7 or newer is required"; return 1
    fi
    for t in blueutil adb cloudflared; do
        have "$t" || echo "optional, not found: $t"
    done
    echo "tools: ok"
    if osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' >/dev/null 2>&1; then
        echo "accessibility: ok"
    else
        echo "accessibility: not granted. Open System Settings > Privacy & Security > Accessibility,"
        echo "               turn on your terminal app, then run this again."
        return 3
    fi
    return 0
}

setup() {
    # tools missing -> stop; only Accessibility missing (3) -> keep going,
    # the warning above already says what to turn on.
    local rc=0
    check || rc=$?
    [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ] || exit "$rc"
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
