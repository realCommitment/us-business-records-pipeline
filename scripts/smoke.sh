#!/usr/bin/env bash
# Trigger one retiring_owners run and wait for it. Usage: scripts/smoke.sh [timeout_seconds, default 600]
set -euo pipefail

timeout=${1:-600}
dag=retiring_owners
run_id="smoke__$(date -u +%Y%m%dT%H%M%SZ)"

curl -fsS http://localhost:8080/api/v2/monitor/health >/dev/null
astro dev run dags unpause "$dag" >/dev/null
astro dev run dags trigger "$dag" -r "$run_id" >/dev/null

deadline=$((SECONDS + timeout))
while true; do
  runs=$(astro dev run dags list-runs "$dag" -o json) || { echo "list-runs failed: $runs" >&2; exit 1; }
  # astro dev run prints the Airflow CLI's warnings on stdout too; keep only the JSON line
  state=$(grep '^\[' <<<"$runs" | jq -r --arg id "$run_id" '.[] | select(.run_id == $id) | .state') ||
    { echo "no JSON in list-runs output: $runs" >&2; exit 1; }
  case "$state" in
    success) echo "$dag $run_id: success"; exit 0 ;;
    failed) echo "$dag $run_id: failed" >&2; exit 1 ;;
  esac
  if ((SECONDS >= deadline)); then
    echo "$dag $run_id: still '${state}' after ${timeout}s" >&2
    exit 1
  fi
  sleep 15
done
