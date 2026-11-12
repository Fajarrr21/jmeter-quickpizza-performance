"""Self-check for sla_check.py. Run: python scripts/test_sla_check.py"""
from sla_check import breaches, percentile, summarise


def row(label, elapsed, ok=True, ts=0):
    return {"label": label, "elapsed": str(elapsed), "success": "true" if ok else "false", "timeStamp": str(ts)}


assert percentile(list(range(1, 101)), 95) == 95
assert percentile([7], 99) == 7
assert percentile([], 95) == 0

# setUp samples are ignored; a fast, error-free request passes.
stats = summarise([row("00 setUp register user", 9999), *[row("05 Browse doughs", 10, ts=i) for i in range(100)]])
assert [s["label"] for s in stats] == ["05 Browse doughs"]
assert breaches(stats) == []

# Slow p95 and >1% errors are both reported.
slow = [row("02 Get recommendation", 100) for _ in range(90)] + [row("02 Get recommendation", 900, ok=False) for _ in range(10)]
found = breaches(summarise(slow))
assert any("p95 900 ms > 500 ms" in b for b in found), found
assert any("errors 10.00%" in b for b in found), found

print("sla_check self-test: OK")
