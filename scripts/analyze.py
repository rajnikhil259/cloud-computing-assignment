"""Summaries for the Task 4 / Task 7 evidence (standard library only).

  python scripts/analyze.py locust PREFIX                  -> PREFIX_summary.json from PREFIX_stats.csv
  python scripts/analyze.py share HEADERS_JSON             -> per-replica / per-version share of successes
  python scripts/analyze.py coldstart PODS_JSON OLD_NAMES  -> creation -> Ready seconds for the new pods
  python scripts/analyze.py coldstart-summary DIR          -> DIR/coldstart_summary.json (median over runs)
  python scripts/analyze.py cost STATS_CSV RATE_CARD REPLICAS CPU_LIMIT MEM_GIB
  python scripts/analyze.py slo STATS_CSV TARGET_PERCENT
"""
import csv
import glob
import json
import os
import statistics
import sys
from datetime import datetime


def aggregated(stats_csv):
    with open(stats_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = next(r for r in rows if r["Name"] == "Aggregated")
    n, fails = int(row["Request Count"]), int(row["Failure Count"])
    return {
        "requests": n,
        "failures": fails,
        "successes": n - fails,
        "failure_rate_percent": round(100.0 * fails / n, 3) if n else None,
        "p50_ms": float(row["50%"]),
        "p95_ms": float(row["95%"]),
        "p99_ms": float(row["99%"]),
        "max_ms": float(row["Max Response Time"]),
        "requests_per_second": round(float(row["Requests/s"]), 3),
    }


def cmd_locust(prefix):
    s = aggregated(prefix + "_stats.csv")
    with open(prefix + "_summary.json", "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    print(json.dumps(s, indent=2))


def cmd_share(headers_json):
    with open(headers_json, encoding="utf-8") as f:
        h = json.load(f)
    out = {}
    for key in ("per_replica", "per_model_version"):
        total = sum(h.get(key, {}).values())
        out[key] = {k: {"requests": v, "share_percent": round(100.0 * v / total, 2)} for k, v in h.get(key, {}).items()}
    out["successful_requests"] = sum(h.get("per_replica", {}).values())
    shares = [v["share_percent"] for v in out["per_replica"].values()]
    out["min_replica_share_percent"] = min(shares) if shares else None
    print(json.dumps(out, indent=2))


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def cmd_coldstart(pods_json, old_names_file):
    with open(old_names_file, encoding="utf-8") as f:
        old = set(f.read().split())
    with open(pods_json, encoding="utf-8") as f:
        pods = json.load(f)["items"]
    res = []
    for p in pods:
        name = p["metadata"]["name"]
        if name in old or p["metadata"].get("deletionTimestamp"):
            continue
        ready = next((c for c in p["status"].get("conditions", []) if c["type"] == "Ready" and c["status"] == "True"),
                     None)
        if ready:
            created = ts(p["metadata"]["creationTimestamp"])
            res.append({"pod": name, "created": p["metadata"]["creationTimestamp"],
                        "ready": ready["lastTransitionTime"],
                        "seconds_to_ready": (ts(ready["lastTransitionTime"]) - created).total_seconds()})
    print(json.dumps(res, indent=2))


def cmd_coldstart_summary(directory):
    runs = []
    for path in sorted(glob.glob(os.path.join(directory, "coldstart_run*_pods.json"))):
        with open(path, encoding="utf-8") as f:
            pods = json.load(f)
        secs = [p["seconds_to_ready"] for p in pods]
        runs.append({"run": os.path.basename(path).split("_")[1], "pods": pods,
                     "slowest_pod_seconds": max(secs), "mean_pod_seconds": round(statistics.mean(secs), 2)})
    summary = {
        "definition": "seconds from Pod creationTimestamp to its Ready condition (k8s timestamps, 1 s resolution)",
        "runs": runs,
        "median_over_runs_slowest_pod_seconds": statistics.median(r["slowest_pod_seconds"] for r in runs),
        "median_over_all_pods_seconds": statistics.median(p["seconds_to_ready"] for r in runs for p in r["pods"]),
    }
    with open(os.path.join(directory, "coldstart_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


def cmd_cost(stats_csv, rate_card, replicas, cpu_limit, mem_gib):
    s = aggregated(stats_csv)
    with open(rate_card, encoding="utf-8") as f:
        rc = json.load(f)
    replicas, cpu_limit, mem_gib = int(replicas), float(cpu_limit), float(mem_gib)
    per_replica = cpu_limit * rc["vcpu_hour"] + mem_gib * rc["gib_memory_hour"]
    hourly = replicas * per_replica
    per_hour = s["requests_per_second"] * 3600
    cost = hourly / per_hour * 1000
    out = {
        "currency": rc["currency"],
        "inputs": {"replicas": replicas, "cpu_limit_vcpu": cpu_limit, "memory_limit_gib": mem_gib,
                   "vcpu_hour": rc["vcpu_hour"], "gib_memory_hour": rc["gib_memory_hour"],
                   "measured_requests_per_second": s["requests_per_second"]},
        "steps": [
            f"per replica per hour = {cpu_limit} vCPU x {rc['vcpu_hour']} + {mem_gib} GiB x {rc['gib_memory_hour']}"
            f" = {per_replica:.4f} {rc['currency']}",
            f"all replicas per hour = {replicas} x {per_replica:.4f} = {hourly:.4f} {rc['currency']}",
            f"requests served per hour = {s['requests_per_second']} req/s x 3600 = {per_hour:.1f}",
            f"cost per 1,000 requests = {hourly:.4f} / {per_hour:.1f} x 1000 = {cost:.4f} {rc['currency']}",
        ],
        "hourly_cost": round(hourly, 4),
        "requests_per_hour": round(per_hour, 1),
        "cost_per_1000_requests": round(cost, 4),
    }
    print(json.dumps(out, indent=2))


def cmd_slo(stats_csv, target):
    s = aggregated(stats_csv)
    target = float(target)
    budget = s["requests"] * (100 - target) / 100
    out = {
        "slo": f"{target}% of POST /parse requests return HTTP 200 within 30 s",
        "window": "one standard load-test run (4 users, 2 minutes)",
        "requests": s["requests"], "failures": s["failures"],
        "error_budget_requests": round(budget, 2),
        "budget_used_requests": s["failures"],
        "budget_used_percent": round(100 * s["failures"] / budget, 2) if budget else None,
        "slo_met": s["failures"] <= budget,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    fn = {"locust": cmd_locust, "share": cmd_share, "coldstart": cmd_coldstart,
          "coldstart-summary": cmd_coldstart_summary, "cost": cmd_cost, "slo": cmd_slo}.get(cmd)
    if not fn:
        sys.exit(__doc__)
    fn(*args)
