"""Summarise a JMeter CSV result file (.jtl) and fail the build when an SLA is breached.

Usage: python scripts/sla_check.py results/load/results.jtl [--markdown out.md]
Exit code 0 = all SLAs met, 1 = at least one breach.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict

# p95 latency budget per request (ms). Labels not listed use DEFAULT_P95_MS.
P95_MS = {
    "01 Login": 800,  # password hashing makes login intentionally slower
    "02 Get recommendation": 500,
}
DEFAULT_P95_MS = 300
MAX_ERROR_RATE = 1.0  # percent, per request and overall
IGNORED_PREFIX = "00 "  # setUp samples (user registration) are not part of the measured load


def percentile(values, p):
    """Nearest-rank percentile on a sorted list."""
    if not values:
        return 0
    return values[max(0, math.ceil(p / 100 * len(values)) - 1)]


def summarise(rows):
    by_label = defaultdict(list)
    for r in rows:
        if not r["label"].startswith(IGNORED_PREFIX):
            by_label[r["label"]].append(r)

    stats = []
    for label, samples in sorted(by_label.items()):
        elapsed = sorted(int(s["elapsed"]) for s in samples)
        errors = sum(s["success"] != "true" for s in samples)
        start = min(int(s["timeStamp"]) for s in samples)
        end = max(int(s["timeStamp"]) + int(s["elapsed"]) for s in samples)
        stats.append({
            "label": label,
            "count": len(samples),
            "error_pct": 100 * errors / len(samples),
            "avg": sum(elapsed) / len(elapsed),
            "p50": percentile(elapsed, 50),
            "p90": percentile(elapsed, 90),
            "p95": percentile(elapsed, 95),
            "p99": percentile(elapsed, 99),
            "max": elapsed[-1],
            "rps": len(samples) / max((end - start) / 1000, 0.001),
            "p95_budget": P95_MS.get(label, DEFAULT_P95_MS),
        })
    return stats


def breaches(stats):
    out = []
    for s in stats:
        if s["p95"] > s["p95_budget"]:
            out.append(f'{s["label"]}: p95 {s["p95"]} ms > {s["p95_budget"]} ms')
        if s["error_pct"] > MAX_ERROR_RATE:
            out.append(f'{s["label"]}: errors {s["error_pct"]:.2f}% > {MAX_ERROR_RATE}%')
    return out


def to_markdown(stats, failed):
    lines = [
        "| Request | Samples | Error % | Avg | p50 | p90 | p95 (budget) | p99 | Max | Req/s | SLA |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for s in stats:
        ok = s["p95"] <= s["p95_budget"] and s["error_pct"] <= MAX_ERROR_RATE
        lines.append(
            f'| {s["label"]} | {s["count"]} | {s["error_pct"]:.2f} | {s["avg"]:.0f} | {s["p50"]} | {s["p90"]} '
            f'| {s["p95"]} ({s["p95_budget"]}) | {s["p99"]} | {s["max"]} | {s["rps"]:.1f} | {"PASS" if ok else "FAIL"} |'
        )
    lines.append("")
    lines.append("**Result: " + ("FAIL, SLA breached**\n\n- " + "\n- ".join(failed) if failed else "PASS, all SLAs met**"))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jtl")
    ap.add_argument("--markdown", help="also write the table to this file (e.g. $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()

    with open(args.jtl, newline="", encoding="utf-8") as f:
        stats = summarise(csv.DictReader(f))
    if not stats:
        sys.exit(f"No measured samples in {args.jtl}")

    failed = breaches(stats)
    md = to_markdown(stats, failed)
    print(md)
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as f:
            f.write(md)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
