#!/usr/bin/env bash
# Run one test profile in non-GUI mode, build the HTML dashboard, then enforce the SLA.
# Usage:   scripts/run.sh <smoke|load|stress|spike|soak> [extra JMeter args, e.g. -Jhost=10.0.0.5]
# Needs:   JMeter on PATH, or JMETER_HOME set. A JDK 17+ (set JAVA_HOME if `java` is a Windows shim).
set -euo pipefail
cd "$(dirname "$0")/.."

JMETER="${JMETER_HOME:+$JMETER_HOME/bin/}jmeter"
PROFILE="${1:-smoke}"
shift || true

run() {
  local name=$1; shift
  local out="results/$name"
  rm -rf "$out"
  echo "=== $name ==="
  "$JMETER" -n -t test-plans/quickpizza.jmx \
    -l "$out/results.jtl" -j "$out/jmeter.log" \
    -e -o "$out/dashboard" \
    -Jjmeter.reportgenerator.sample_filter='^0[1-9].*' \
    "$@"
  python scripts/sla_check.py "$out/results.jtl" --markdown "$out/summary.md"
}

case "$PROFILE" in
  smoke)  run smoke -Jthreads=5   -Jrampup=5  -Jduration=30  "$@" ;;
  load)   run load  -Jthreads="${LOAD_USERS:-20}" -Jrampup=30 -Jduration=180 "$@" ;;
  spike)  run spike -Jthreads=300 -Jrampup=5  -Jduration=60  "$@" ;;
  soak)   run soak  -Jthreads=30  -Jrampup=30 -Jduration=900 "$@" ;;
  stress)
    # Step the load up; the first step that breaks the SLA is the capacity limit.
    for users in 10 20 30 40 50 75 100; do
      if ! run "stress-$users" -Jthreads="$users" -Jrampup=20 -Jduration=60 "$@"; then
        echo ">>> SLA first broken at $users concurrent users"
        exit 1
      fi
    done
    echo ">>> SLA held up to 100 concurrent users" ;;
  *) echo "Unknown profile '$PROFILE'. Use smoke|load|stress|spike|soak." >&2; exit 2 ;;
esac
