"""Run a model over a JSONL file of commands and write raw predictions for tools/score.py.

  python training/predict.py --model artifacts/models/v1 --input data/validation.jsonl \
      --output results/student_v1_validation_predictions.jsonl
  python training/predict.py --model EleutherAI/pythia-70m --revision <sha> ...   (untrained base)

Each output line is {"id": "V001", "prediction": "<the raw text the model produced>"}.
Uses exactly the same prompt and greedy decoding as the service (service/model.py).
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "service"))

from model import CommandParser  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="local model directory or Hugging Face id")
    ap.add_argument("--revision", help="Hugging Face revision when --model is a hub id")
    ap.add_argument("--input", default=os.path.join(ROOT, "data/validation.jsonl"))
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()

    model_dir = a.model
    if not os.path.isdir(model_dir):
        from huggingface_hub import snapshot_download

        model_dir = snapshot_download(a.model, revision=a.revision,
                                      allow_patterns=["*.json", "*.safetensors", "*.txt"])
    parser = CommandParser(model_dir, threads=a.threads)
    rows = [json.loads(line) for line in open(a.input, encoding="utf-8") if line.strip()]
    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    t0 = time.time()
    with open(a.output, "w", encoding="utf-8") as f:
        for r in rows:
            pred = parser.generate(r["text"], a.max_new_tokens)
            f.write(json.dumps({"id": r["id"], "prediction": pred}, ensure_ascii=False) + "\n")
    dt = time.time() - t0
    print(f"{len(rows)} predictions in {dt:.1f}s ({1000 * dt / len(rows):.0f} ms each) -> {a.output}")


if __name__ == "__main__":
    main()
