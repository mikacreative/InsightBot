#!/usr/bin/env bash
set -euo pipefail

health_url="${1:?Usage: bash scripts/check_streamlit_health.sh HEALTH_URL}"

for attempt in $(seq 1 12); do
  if http_status="$(curl --disable --silent --show-error --connect-timeout 2 --max-time 5 \
    --output /dev/null --write-out '%{http_code}' "$health_url")"; then
    if [ "$http_status" = "200" ]; then
      echo "Streamlit HTTP health check passed (HTTP 200)"
      exit 0
    fi
    echo "Streamlit health attempt $attempt/12 returned HTTP $http_status" >&2
  else
    echo "Streamlit health attempt $attempt/12 failed (curl exit $?)" >&2
  fi

  if [ "$attempt" -lt 12 ]; then
    sleep 5
  fi
done

echo "Streamlit HTTP health check failed after retries" >&2
exit 1
