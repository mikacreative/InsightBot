#!/bin/bash
# Run the isolated local prototype. Optional --model-config reads existing AI
# settings only; no existing Signal Desk state or credentials are modified.
set -eu
POC_REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POC_PYTHON="${SIGNAL_DESK_POC_PYTHON:-$POC_REPO_ROOT/.venv-signal-desk/bin/python}"
cd "$POC_REPO_ROOT"
[ -x "$POC_PYTHON" ] || { echo 'Use the isolated Signal Desk Python environment.'; exit 1; }
if [ "${1:-}" = --help ]; then
  exec "$POC_PYTHON" -m insightbot.signal_desk.prototype_poc --help
fi
[ -f frontend/signal-desk-workflow-poc/dist/index.html ] || {
  echo 'Build frontend/signal-desk-workflow-poc first; see docs/signal-desk/LOCAL-V02.md.'
  exit 1
}
"$POC_PYTHON" scripts/signal-desk-kestra-runtime.py start --timeout 55
exec "$POC_PYTHON" -m insightbot.signal_desk.prototype_poc "$@"
