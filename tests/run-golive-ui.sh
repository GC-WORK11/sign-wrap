#!/bin/sh
# run-golive-ui.sh — regression test for "Go Live doesn't work": the first
# open covered the camera with a card and tracked nothing until a cold load
# of the hand model finished (8.6 s measured by QA), a stale replay flag could
# swap the camera for someone else's frames, and a stuck load spun forever.
#
#   1. serves tests/stub_wfd.py + web/ on a local port
#   2. headless Chrome with its fake camera runs /golivetest: the real app and
#      the real vendored hand model (see tests/golive.html for the checks)
#
# Needs: python3, google-chrome (or chromium). No node, no deps.
# Usage: tests/run-golive-ui.sh [port]   exit 0 = pass
#        WF_UI_TIMEOUT=900 tests/run-golive-ui.sh   (seconds; slow machines)
set -u
cd "$(dirname "$0")/.."
PORT="${1:-8748}"
BASE_RESULT="${WF_STUB_RESULT:-/tmp/wf-golive-result.json}"
RESULT="$BASE_RESULT.golive"
PROFILE="${TMPDIR:-/tmp}/wf-chrome-golive-$PORT"
T="${WF_UI_TIMEOUT:-240}"
rm -f "$RESULT"
CHROME_BIN="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
[ -n "$CHROME_BIN" ] || { echo "no chrome/chromium found"; exit 2; }

pkill -f "user-data-dir=$PROFILE" 2>/dev/null
rm -rf "$PROFILE"
WF_STUB_RESULT="$BASE_RESULT" python3 tests/stub_wfd.py --port "$PORT" >/tmp/wf-stub-golive.log 2>&1 &
STUB=$!
CPID=""
cleanup() { for p in "$STUB" "$CPID"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; rm -rf "$PROFILE"; }
trap cleanup EXIT

i=0; while [ $i -lt 60 ]; do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  i=$((i+1)); sleep 0.1
done

timeout "$T" "$CHROME_BIN" --headless=new --no-sandbox --no-first-run \
  --user-data-dir="$PROFILE" \
  --use-fake-ui-for-media-stream --use-fake-device-for-media-stream \
  --autoplay-policy=no-user-gesture-required \
  "http://127.0.0.1:$PORT/golivetest" >/tmp/wf-chrome-golive.log 2>&1 &
CPID=$!

i=0; while [ $i -lt $((T * 10)) ]; do [ -f "$RESULT" ] && break; i=$((i+1)); sleep 0.1; done
kill "$CPID" 2>/dev/null; CPID=""
[ -f "$RESULT" ] || { echo "FAIL: no result posted"; tail -20 /tmp/wf-chrome-golive.log; exit 1; }
python3 - "$RESULT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
for s in r.get("steps", []):
    print("  ·", s)
if r.get("errs"):
    print("  errors:", *r["errs"], sep="\n    ")
sys.exit(0 if r.get("pass") else 1)
PY
rc=$?
[ $rc -eq 0 ] && echo "GOLIVE PASS" || echo "GOLIVE FAIL"
exit $rc
