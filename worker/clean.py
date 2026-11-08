"""Clean the raw teacher replies into the training set (Task 1, step 6).

Reads every shard-*.jsonl written by the workers, keeps the records in id order and removes:
  (a) replies that are not valid JSON;
  (b) replies whose keys are not exactly intent, date, time and place;
  (c) replies whose intent is not one of the eight;
  (d) replies with a slot value that is neither null nor text that appears in the command;
  (e) duplicate commands (the copy with the smallest id is kept).
Checks (a)-(d) are applied first, in that order, so each rejected record is counted under the
first rule it breaks. Duplicates (e) are then found among the records that passed (a)-(d):
records are visited in id order, so the copy with the smallest id is the one that is kept.
Command texts are compared after lower-casing and collapsing white space.

Writes train.jsonl (one line per kept record, in id order) and train.sha256 (SHA-256 of the
exact bytes of train.jsonl), plus clean_report.json with the counts and rejected.jsonl.
Every kept line is {"id", "text", "teacher_raw", "teacher_json"}: teacher_raw is the teacher's
reply exactly as generated, teacher_json is the same object re-serialised on one line with the
keys in schema order (values untouched); it is the training target.

Usage
  python worker/clean.py --input-dir datasets/teacher --output-dir datasets/v1 \
      [--pool data/commands_pool.jsonl] [--report results/clean_report.json]
  python clean.py --s3      (inside the cluster: s3://datasets/teacher/ -> s3://datasets/v1/)
The local mode needs only the Python standard library.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys

KEYS = ("intent", "date", "time", "place")
SLOTS = ("date", "time", "place")
INTENTS = (
    "alarm_set", "alarm_query", "calendar_set", "calendar_query",
    "calendar_remove", "weather_query", "datetime_query", "recommendation_events",
)
REASONS = ("a_invalid_json", "b_wrong_keys", "c_bad_intent", "d_bad_slot", "e_duplicate")


def norm(s):
    return " ".join(str(s).lower().split())


def check_reply(text, raw):
    """Return (reason, parsed). reason is None when the reply passes rules (a)-(d)."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "a_invalid_json", None
    if not isinstance(obj, dict) or set(obj.keys()) != set(KEYS) or len(obj) != len(KEYS):
        return "b_wrong_keys", None
    if not isinstance(obj["intent"], str) or obj["intent"] not in INTENTS:
        return "c_bad_intent", None
    for k in SLOTS:
        v = obj[k]
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or norm(v) not in norm(text):
            return "d_bad_slot", None
    return None, obj


def id_key(rid):
    """Sort ids such as C0001 ... C3000 in numeric order (and anything else as text)."""
    m = re.match(r"^(\D*)(\d+)$", rid)
    return (m.group(1), int(m.group(2)), rid) if m else (rid, -1, rid)


def clean(records):
    """records: iterable of {"id", "text", "teacher_raw"}. Returns (kept, rejected, counts)."""
    rows = sorted(records, key=lambda r: id_key(r["id"]))
    counts = {"input_records": len(rows), **{r: 0 for r in REASONS}, "kept": 0}
    kept, rejected, seen = [], [], {}
    for r in rows:
        reason, obj = check_reply(r["text"], r["teacher_raw"])
        if reason is None:
            t = norm(r["text"])
            if t in seen:
                reason = "e_duplicate"
            else:
                seen[t] = r["id"]
        if reason:
            counts[reason] += 1
            rejected.append({"id": r["id"], "reason": reason, "text": r["text"],
                             "teacher_raw": r["teacher_raw"],
                             **({"duplicate_of": seen[norm(r["text"])]} if reason == "e_duplicate" else {})})
            continue
        canonical = json.dumps({k: obj[k] for k in KEYS}, ensure_ascii=False)
        kept.append({"id": r["id"], "text": r["text"], "teacher_raw": r["teacher_raw"],
                     "teacher_json": canonical})
    counts["kept"] = len(kept)
    counts["identity_holds"] = counts["input_records"] == sum(counts[r] for r in REASONS) + counts["kept"]
    return kept, rejected, counts


def to_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def coverage(shards, pool_ids):
    """Every pool id must appear in exactly one shard: report gaps and repeats."""
    where = {}
    for name, rows in shards.items():
        for r in rows:
            where.setdefault(r["id"], []).append(name)
    repeated = sorted((i for i, s in where.items() if len(s) > 1), key=id_key)
    missing = sorted((i for i in pool_ids if i not in where), key=id_key) if pool_ids is not None else None
    unexpected = sorted((i for i in where if i not in set(pool_ids)), key=id_key) if pool_ids is not None else None
    return {"shards": {n: len(r) for n, r in shards.items()}, "records_in_shards": sum(len(r) for r in shards.values()),
            "pool_records": len(pool_ids) if pool_ids is not None else None,
            "missing_ids": missing, "repeated_ids": repeated, "unexpected_ids": unexpected,
            "ok": not repeated and not missing and not unexpected}


def build_outputs(shards, pool_ids):
    records = [r for rows in shards.values() for r in rows]
    kept, rejected, counts = clean(records)
    train = to_jsonl(kept)
    digest = hashlib.sha256(train.encode("utf-8")).hexdigest()
    report = {**counts, "train_sha256": digest,
              "first_1500_last_id": kept[min(1500, len(kept)) - 1]["id"] if kept else None,
              "coverage": coverage(shards, pool_ids)}
    return train, f"{digest}  train.jsonl\n", report, to_jsonl(rejected)


def parse_jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def shard_sort_key(name):
    m = re.search(r"shard-(\d+)\.jsonl$", name)
    return int(m.group(1)) if m else -1


def run_local(a):
    paths = sorted(glob.glob(os.path.join(a.input_dir, "shard-*.jsonl")), key=shard_sort_key)
    if not paths:
        sys.exit(f"no shard-*.jsonl files in {a.input_dir}")
    shards = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            shards[os.path.basename(p)] = parse_jsonl(f.read())
    pool_ids = None
    if a.pool and os.path.exists(a.pool):
        with open(a.pool, encoding="utf-8") as f:
            pool_ids = [r["id"] for r in parse_jsonl(f.read())]
    train, sha, report, rejected = build_outputs(shards, pool_ids)
    os.makedirs(a.output_dir, exist_ok=True)
    for name, body in (("train.jsonl", train), ("train.sha256", sha)):
        with open(os.path.join(a.output_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    report_path = a.report or os.path.join(a.output_dir, "clean_report.json")
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    with open(os.path.splitext(report_path)[0].replace("clean_report", "clean_rejected") + ".jsonl",
              "w", encoding="utf-8", newline="\n") as f:
        f.write(rejected)
    return report


def run_s3(a):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import s3util

    s3 = s3util.client()
    keys = [k for k in s3util.list_keys(s3, a.bucket, a.shard_prefix) if re.search(r"shard-\d+\.jsonl$", k)]
    if not keys:
        sys.exit(f"no shard objects under s3://{a.bucket}/{a.shard_prefix}")
    keys.sort(key=shard_sort_key)
    shards = {os.path.basename(k): parse_jsonl(s3util.get_text(s3, a.bucket, k)) for k in keys}
    pool_text = s3util.get_text_or_none(s3, a.bucket, "commands_pool.jsonl")
    pool_ids = [r["id"] for r in parse_jsonl(pool_text)] if pool_text else None
    train, sha, report, rejected = build_outputs(shards, pool_ids)
    out = a.output_prefix
    s3util.put_text(s3, a.bucket, out + "train.jsonl", train)
    s3util.put_text(s3, a.bucket, out + "train.sha256", sha, "text/plain")
    s3util.put_text(s3, a.bucket, out + "clean_report.json", json.dumps(report, indent=2) + "\n", "application/json")
    s3util.put_text(s3, a.bucket, out + "rejected.jsonl", rejected)
    print("read:", ", ".join(f"s3://{a.bucket}/{k}" for k in keys))
    print(f"wrote s3://{a.bucket}/{out}train.jsonl and train.sha256")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", default="datasets/teacher")
    ap.add_argument("--output-dir", default="datasets/v1")
    ap.add_argument("--pool", default="data/commands_pool.jsonl", help="for the no-gaps/no-repeats coverage check")
    ap.add_argument("--report", help="where to write clean_report.json (default: OUTPUT_DIR/clean_report.json)")
    ap.add_argument("--s3", action="store_true", help="read and write the datasets bucket instead of local files")
    ap.add_argument("--bucket", default="datasets")
    ap.add_argument("--shard-prefix", default="teacher/")
    ap.add_argument("--output-prefix", default="v1/")
    a = ap.parse_args(argv)
    report = run_s3(a) if a.s3 else run_local(a)
    print(json.dumps(report, indent=2))
    if not report["identity_holds"]:
        sys.exit("count identity does not hold")


if __name__ == "__main__":
    main()
