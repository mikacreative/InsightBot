#!/bin/bash
# User-scoped Mac mini test service. Never touches production or existing state.
set -eu
ROOT="${SIGNAL_DESK_TEST_ROOT:-$HOME/Applications/SignalDesk-test}"
RELEASE="$ROOT/releases/20260930"
LABEL="com.mikawang.signal-desk-test"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
case "${1:-status}" in
  run)
    umask 077
    if [ -f "$ROOT/config.env" ]; then set -a; . "$ROOT/config.env"; set +a; fi
    if [ -f "$ROOT/network.env" ]; then set -a; . "$ROOT/network.env"; set +a; fi
    if [ "${SIGNAL_DESK_STATE_DIR:-}" = /absolute/private/path/signal-desk-state ]; then
      unset SIGNAL_DESK_STATE_DIR
    fi
    export SIGNAL_DESK_STATE_DIR="${SIGNAL_DESK_STATE_DIR:-$ROOT/state}"
    export SIGNAL_DESK_INPUT_FILE="${SIGNAL_DESK_INPUT_FILE:-$ROOT/state/sunlife-replay.json}"
    export LANGGRAPH_STRICT_MSGPACK=true
    cd "$RELEASE"
    exec "$ROOT/venv/bin/python" -m insightbot.signal_desk --state-dir "$SIGNAL_DESK_STATE_DIR" serve --host 127.0.0.1 --port 18876
    ;;
  install)
    [ "$(uname -s)" = Darwin ] || { echo 'This installer requires macOS.'; exit 1; }
    [ -x "$ROOT/venv/bin/python" ] || { echo 'Missing test virtual environment.'; exit 1; }
    [ -f "$RELEASE/scripts/signal-desk-service.sh" ] || { echo 'Missing 20260930 test release.'; exit 1; }
    umask 077
    mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
    # plistlib escapes filesystem paths; no API credentials are copied to the plist.
    "$ROOT/venv/bin/python" - "$ROOT" "$RELEASE" "$PLIST" "$LABEL" <<'PY'
import os, plistlib, sys
root, release, path, label = sys.argv[1:]
config = {
    'Label': label,
    'ProgramArguments': ['/bin/bash', release + '/scripts/signal-desk-service.sh', 'run'],
    'WorkingDirectory': release,
    'EnvironmentVariables': {'SIGNAL_DESK_TEST_ROOT': root},
    'RunAtLoad': True,
    'KeepAlive': True,
    'ThrottleInterval': 15,
    'StandardOutPath': root + '/logs/service.stdout.log',
    'StandardErrorPath': root + '/logs/service.stderr.log',
    'Umask': 63,
}
if os.path.exists(path):
    with open(path, 'rb') as f:
        old = plistlib.load(f)
    if old.get('Label') != label or old.get('EnvironmentVariables', {}).get('SIGNAL_DESK_TEST_ROOT') != root:
        raise SystemExit('Existing plist is not this test installation; left unchanged.')
with open(path, 'wb') as f:
    plistlib.dump(config, f)
os.chmod(path, 0o600)
PY
    plutil -lint "$PLIST"
    echo 'Installed test LaunchAgent. Stop the old manual server, then run start.'
    ;;
  start)
    [ -f "$PLIST" ] || { echo 'Run install first.'; exit 1; }
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo 'LaunchAgent already loaded. Use status, or stop then start after configuration changes.'
    else
      launchctl enable "$DOMAIN/$LABEL"
      launchctl bootstrap "$DOMAIN" "$PLIST"
      echo 'Loaded test LaunchAgent; inspect status and health before use.'
    fi
    ;;
  stop)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl bootout "$DOMAIN/$LABEL"
    fi
    launchctl disable "$DOMAIN/$LABEL"
    echo 'Test LaunchAgent stopped and disabled for future login. State and configuration preserved.'
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL"
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18876/health
    printf '\n'
    ;;
  *) echo 'Usage: signal-desk-service.sh install|start|stop|status|run'; exit 2 ;;
esac
