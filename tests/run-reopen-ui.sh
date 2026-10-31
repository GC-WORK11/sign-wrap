#!/bin/sh
# run-reopen-ui.sh — regression test for "Teach never starts" / "Go Live
# tracks nothing the second time".
#
#   1. serves tests/stub_wfd.py + web/ on a local port
#   2. headless Chrome with its fake camera runs /reopentest: the real app,
#      the real vendored hand model, Go Live -> close -> Teach -> Go Live
#   3. passes only when every step keeps sending /live/kp frames
#
# Needs: python3, google-chrome (or chromium). No node, no deps.
# Usage: tests/run-reopen-ui.sh [port]   exit 0 = pass
set -u
cd "$(dirname "$0")/.."
PORT="${1:-8746}"
BASE_RESULT="${WF_STUB_RESULT:-/tmp/wf-reopen-result.json}"
RESULT="$BASE_RESULT.reopen"
PROFILE="${TMPDIR:-/tmp}/wf-chrome-reopen-$PORT"
rm -f "$RESULT"
CHROME_BIN="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
[ -n "$CHROME_BIN" ] || { echo "no chrome/chromium found"; exit 2; }

pkill -f "user-data-dir=$PROFILE" 2>/dev/null
rm -rf "$PROFILE"
WF_STUB_RESULT="$BASE_RESULT" python3 tests/stub_wfd.py --port "$PORT" >/tmp/wf-stub-reopen.log 2>&1 &
STUB=$!
CPID=""
cleanup() { for p in "$STUB" "$CPID"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; rm -rf "$PROFILE"; }
trap cleanup EXIT

i=0; while [ $i -lt 60 ]; do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  i=$((i+1)); sleep 0.1
done

timeout 150 "$CHROME_BIN" --headless=new --no-sandbox --no-first-run \
  --user-data-dir="$PROFILE" \
  --use-fake-ui-for-media-stream --use-fake-device-for-media-stream \
  --autoplay-policy=no-user-gesture-required \
  "http://127.0.0.1:$PORT/reopentest" >/tmp/wf-chrome-reopen.log 2>&1 &
CPID=$!

i=0; while [ $i -lt 1400 ]; do [ -f "$RESULT" ] && break; i=$((i+1)); sleep 0.1; done
kill "$CPID" 2>/dev/null; CPID=""
[ -f "$RESULT" ] || { echo "FAIL: no result posted"; tail -20 /tmp/wf-chrome-reopen.log; exit 1; }
python3 - "$RESULT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
for s in r.get("steps", []):
    print("  ·", s)
print("  frames sent per step:", r.get("kp"))
if r.get("errs"):
    print("  errors:", *r["errs"], sep="\n    ")
sys.exit(0 if r.get("pass") else 1)
PY
rc=$?
[ $rc -eq 0 ] && echo "REOPEN PASS" || echo "REOPEN FAIL"
exit $rc
