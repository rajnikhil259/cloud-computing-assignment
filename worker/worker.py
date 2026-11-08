"""Teacher-labelling worker (Task 1).

Reads two environment variables:
  SHARD_INDEX  this worker's shard, starting from 0
  SHARD_COUNT  total number of shards
and takes every command whose line number n (counting from 0) in the input file satisfies
n % SHARD_COUNT == SHARD_INDEX. Each command is sent to the teacher (phi3.5 on Ollama,
temperature 0, seed 42) with the prompt in prompts/teacher_prompt.txt, and one line
  {"id": "...", "text": "...", "teacher_raw": "<the teacher's exact reply>"}
is written to this worker's own object, e.g. s3://datasets/teacher/shard-0.jsonl.

The object is re-uploaded every CHECKPOINT_EVERY records, and a restarted worker
resumes from what is already in its object, so a pod restart never loses or repeats work.

Other settings (all optional, with defaults for the in-cluster deployment):
  S3_ENDPOINT, INPUT_BUCKET (datasets), INPUT_KEY (commands_pool.jsonl),
  OUTPUT_BUCKET (datasets), OUTPUT_PREFIX (teacher/), OLLAMA_URL, TEACHER_MODEL (phi3.5),
  PROMPT_FILE, CHECKPOINT_EVERY (25), REQUEST_TIMEOUT (600)
"""
import json
import os
import sys
import time

import requests

# Fixed teacher settings required by the handout: temperature 0 and seed 42.
TEACHER_OPTIONS = {
    "temperature": 0,
    "seed": 42,
    "num_predict": 128,   # a four-key JSON object needs < 60 tokens; this only caps run-away replies
    "num_ctx": 2048,
}


def select_shard(records, shard_index, shard_count):
    """Records whose 0-based line number leaves remainder shard_index modulo shard_count."""
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError(f"invalid shard {shard_index}/{shard_count}")
    return [r for n, r in enumerate(records) if n % shard_count == shard_index]


def build_prompt(template, command):
    if "{command}" not in template:
        raise ValueError("prompt template must contain the {command} placeholder")
    return template.replace("{command}", command)


def parse_jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def to_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def ask_teacher(session, url, model, prompt, timeout, retries=6):
    payload = {"model": model, "prompt": prompt, "stream": False, "options": TEACHER_OPTIONS}
    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            r = session.post(f"{url.rstrip('/')}/api/generate", json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()["response"]
        except (requests.RequestException, KeyError, ValueError) as e:
            if attempt == retries:
                raise
            print(f"  teacher call failed (attempt {attempt}): {e}; retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 60)


def main():
    import s3util  # imported here so the pure functions above can be tested without boto3

    shard_index = int(os.environ["SHARD_INDEX"])
    shard_count = int(os.environ["SHARD_COUNT"])
    in_bucket = os.environ.get("INPUT_BUCKET", "datasets")
    in_key = os.environ.get("INPUT_KEY", "commands_pool.jsonl")
    out_bucket = os.environ.get("OUTPUT_BUCKET", "datasets")
    out_prefix = os.environ.get("OUTPUT_PREFIX", "teacher/")
    out_key = f"{out_prefix}shard-{shard_index}.jsonl"
    url = os.environ.get("OLLAMA_URL", "http://ollama.pipeline.svc.cluster.local:11434")
    model = os.environ.get("TEACHER_MODEL", "phi3.5")
    every = int(os.environ.get("CHECKPOINT_EVERY", "25"))
    timeout = float(os.environ.get("REQUEST_TIMEOUT", "600"))
    with open(os.environ.get("PROMPT_FILE", "/config/teacher_prompt.txt"), encoding="utf-8") as f:
        template = f.read()

    s3 = s3util.client()
    records = parse_jsonl(s3util.get_text(s3, in_bucket, in_key))
    mine = select_shard(records, shard_index, shard_count)
    print(f"[{os.environ.get('POD_NAME', 'worker')}] shard {shard_index}/{shard_count}: "
          f"{len(mine)} of {len(records)} commands from s3://{in_bucket}/{in_key} -> s3://{out_bucket}/{out_key}",
          flush=True)

    done = parse_jsonl(s3util.get_text_or_none(s3, out_bucket, out_key) or "")
    done_ids = [r["id"] for r in done]
    if done_ids != [r["id"] for r in mine[:len(done)]]:
        sys.exit(f"existing object s3://{out_bucket}/{out_key} does not match this shard; refusing to resume")
    if done:
        print(f"resuming after {len(done)} records already in the shard object", flush=True)

    session = requests.Session()
    t0 = time.time()
    todo = mine[len(done):]
    for i, rec in enumerate(todo, 1):
        t = time.time()
        reply = ask_teacher(session, url, model, build_prompt(template, rec["text"]), timeout)
        done.append({"id": rec["id"], "text": rec["text"], "teacher_raw": reply})
        print(f"{rec['id']} {time.time() - t:5.2f}s {json.dumps(reply, ensure_ascii=False)}", flush=True)
        if i % every == 0 or i == len(todo):
            s3util.put_text(s3, out_bucket, out_key, to_jsonl(done))
            rate = i / max(time.time() - t0, 1e-9)
            print(f"checkpoint: {len(done)}/{len(mine)} records, {rate:.3f} records/s", flush=True)
    if not todo:
        s3util.put_text(s3, out_bucket, out_key, to_jsonl(done))
    print(f"shard {shard_index} complete: {len(done)} records in s3://{out_bucket}/{out_key} "
          f"({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
