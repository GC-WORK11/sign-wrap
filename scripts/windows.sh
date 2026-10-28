#!/usr/bin/env bash
# Sign-Flow setup and launcher for Windows 10/11.
#
# Run this in Git Bash (installed with Git for Windows), not in cmd.exe
# or PowerShell. From cmd or PowerShell, use bin\wrap.cmd or bin\wrap.ps1
# with the same commands instead.
#
#   scripts/windows.sh            check tools, npm install, start the daemon
#   scripts/windows.sh setup      check tools and npm install only
#   scripts/windows.sh check      check tools only (no changes)
#   scripts/windows.sh <command>  pass a command to the wrap CLI:
#                                 start stop restart status pair logs doctor
#                                 send bridge tunnel open install
#
# On Windows the CLI is server/wrap_cli.py, reached through bin/wrap.js.
# Typing uses window messages, so no extra tools or permissions are needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

have() { command -v "$1" >/dev/null 2>&1; }

find_python() {
    # python.org installs `python`, the launcher is `py -3`. The Store
    # alias `python` exists but fails until Python is installed.
    if python --version >/dev/null 2>&1; then echo python; return 0; fi
    if python3 --version >/dev/null 2>&1; then echo python3; return 0; fi
    if py -3 --version >/dev/null 2>&1; then echo "py -3"; return 0; fi
    return 1
}

check() {
    local missing=() py
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) ;;
        *) echo "this script is for Git Bash on Windows; use scripts/linux.sh or scripts/macos.sh"; return 1 ;;
    esac
    have node || missing+=("node")
    have npm || missing+=("npm")
    py="$(find_python)" || missing+=("python")
    have powershell || have powershell.exe || have pwsh || missing+=("powershell")
    if [ ${#missing[@]} -gt 0 ]; then
        echo "missing: ${missing[*]}"
        echo "install Node.js LTS from https://nodejs.org and Python 3 from https://www.python.org"
        echo "(tick 'Add python.exe to PATH'), or: winget install OpenJS.NodeJS.LTS Python.Python.3.12"
        return 1
    fi
    if $py -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)'; then :; else
        echo "python 3.7 or newer is required"; return 1
    fi
    for t in adb cloudflared; do
        have "$t" || echo "optional, not found: $t"
    done
    echo "tools: ok ($py)"
    return 0
}

setup() {
    check
    (cd "$ROOT" && npm install --no-audit --no-fund)
    echo "setup done. Optional: run 'npm link' in $ROOT to put 'wrap' on your PATH."
}

wrap() { (cd "$ROOT" && node bin/wrap.js "$@"); }

cmd="${1:-}"
case "$cmd" in
    "")       setup; wrap start ;;
    setup)    setup ;;
    check)    check ;;
    start|stop|restart|status|pair|logs|doctor|send|bridge|tunnel|open|install)
              wrap "$@" ;;
    -h|--help|help)
              awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0" ;;
    *)        echo "unknown command: $cmd (try: $0 help)"; exit 2 ;;
esac
