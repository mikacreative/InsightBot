#!/bin/bash
# Isolated, manually started Mac mini test service; no system configuration changes.
set -eu
ROOT="${SIGNAL_DESK_TEST_ROOT:-$HOME/Applications/SignalDesk-test}"
RELEASE="$ROOT/releases/20260929"
PIDFILE="$ROOT/signal-desk.pid"
case "${1:-status}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo 'Recorded process is already running; inspect status before restart.'; exit 1
    fi
    if [ -f "$ROOT/config.env" ]; then set -a; . "$ROOT/config.env"; set +a; fi
    export SIGNAL_DESK_STATE_DIR="${SIGNAL_DESK_STATE_DIR:-$ROOT/state}"
    export SIGNAL_DESK_INPUT_FILE="${SIGNAL_DESK_INPUT_FILE:-$ROOT/state/sunlife-replay.json}"
    export LANGGRAPH_STRICT_MSGPACK=true
    umask 077
    cd "$RELEASE"
    nohup "$ROOT/venv/bin/python" -m insightbot.signal_desk --state-dir "$SIGNAL_DESK_STATE_DIR" serve --host 127.0.0.1 --port 18876 > "$ROOT/server.log" 2>&1 < /dev/null &
    echo "$!" > "$PIDFILE"
    echo "Started Signal Desk test process $(cat "$PIDFILE"). Verify /health before use."
    ;;
  stop)
    if [ ! -f "$PIDFILE" ]; then echo 'No recorded test process.'; exit 0; fi
    PID="$(cat "$PIDFILE")"
    case "$(ps -p "$PID" -o command= 2>/dev/null || true)" in
      *"insightbot.signal_desk"*"18876"*) kill "$PID"; rm "$PIDFILE"; echo 'Stopped test service.' ;;
      *) echo 'PID does not match Signal Desk test service; no process stopped.'; exit 1 ;;
    esac
    ;;
  status)
    curl --fail --silent http://127.0.0.1:18876/health
    ;;
  *) echo 'Usage: signal-desk-test.sh start|stop|status'; exit 2 ;;
esac
