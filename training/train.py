"""Fine-tune EleutherAI/pythia-70m on the teacher's replies (sequence-level distillation, Task 2).

Every training example is
    Command: <the command>
    JSON: <the teacher's JSON reply><eos>
and the loss is computed on the JSON reply (and eos) only, so the student learns to produce
the teacher's output given the command. All settings come from training/config.yaml.

  python training/train.py --config training/config.yaml [--version v1] [--subset 50]

Writes <output_dir>/<version>/ (model.safetensors, config.json, tokenizer files, version.json),
the per-epoch loss to training/loss.csv (training/loss_<version>.csv for other versions), and
model.sha256 (sha256sum format) for the files of that directory.
With --subset N only the first N records are used and everything goes to
<output_dir>/subset-<N>/ so the committed results are not overwritten.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path, version):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    version = version or cfg.get("default_version", "v1")
    overrides = (cfg.get("variants") or {}).get(version)
    if overrides is None:
        sys.exit(f"version {version!r} is not defined under 'variants' in {path}")
    cfg.update(overrides)
    cfg["version"] = version
    return cfg


def set_seed(seed):
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def read_records(path, limit):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def build_examples(tokenizer, rows, cfg):
    """Token ids and labels; prompt tokens get label -100 so only the reply is learned."""
    eos = tokenizer.eos_token_id
    examples, truncated = [], 0
    for r in rows:
        prompt = cfg["prompt_template"].format(text=" ".join(r["text"].split()))
        p_ids = tokenizer(prompt).input_ids
        t_ids = tokenizer(" " + r[cfg["target_field"]]).input_ids + [eos]
        ids = (p_ids + t_ids)[: cfg["max_seq_length"]]
        labels = ([-100] * len(p_ids) + t_ids)[: cfg["max_seq_length"]]
        truncated += len(p_ids) + len(t_ids) > cfg["max_seq_length"]
        examples.append((ids, labels))
    return examples, truncated


def batches(examples, batch_size, pad_id, generator):
    import torch

    order = torch.randperm(len(examples), generator=generator).tolist()
    for i in range(0, len(order), batch_size):
        chunk = [examples[j] for j in order[i:i + batch_size]]
        width = max(len(ids) for ids, _ in chunk)
        input_ids = torch.full((len(chunk), width), pad_id, dtype=torch.long)
        labels = torch.full((len(chunk), width), -100, dtype=torch.long)
        mask = torch.zeros((len(chunk), width), dtype=torch.long)
        for k, (ids, lab) in enumerate(chunk):
            input_ids[k, :len(ids)] = torch.tensor(ids)
            labels[k, :len(lab)] = torch.tensor(lab)
            mask[k, :len(ids)] = 1
        yield input_ids, mask, labels


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums(model_dir):
    names = sorted(n for n in os.listdir(model_dir)
                   if n != "model.sha256" and os.path.isfile(os.path.join(model_dir, n)))
    lines = [f"{sha256_file(os.path.join(model_dir, n))}  {n}\n" for n in names]
    with open(os.path.join(model_dir, "model.sha256"), "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    return names


def installed_versions():
    import numpy
    import safetensors
    import tokenizers
    import torch
    import transformers

    return {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__,
            "tokenizers": tokenizers.__version__, "safetensors": safetensors.__version__,
            "numpy": numpy.__version__, "pyyaml": yaml.__version__}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(ROOT, "training/config.yaml"))
    ap.add_argument("--version", help="variant from config.yaml (default: default_version)")
    ap.add_argument("--subset", type=int, default=0, help="train on the first N records only (smoke test)")
    a = ap.parse_args()
    cfg = load_config(a.config, a.version)
    os.chdir(ROOT)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup

    versions = installed_versions()
    for lib, want in cfg["library_versions"].items():
        have = versions.get(lib, "?")
        if not str(have).startswith(str(want).split("+")[0]):
            print(f"WARNING: {lib} {have} installed, config.yaml records {want}")
    torch.set_num_threads(int(cfg.get("num_threads", 4)))
    set_seed(int(cfg["seed"]))  # the seed is fixed here, before the model and data order exist

    limit = a.subset or int(cfg["max_train_records"])
    rows = read_records(cfg["train_file"], limit)
    tag = f"subset-{a.subset}" if a.subset else cfg["version"]
    out_dir = os.path.join(cfg["output_dir"], tag)
    loss_csv = (os.path.join(out_dir, "loss.csv") if a.subset else
                cfg["loss_csv"] if cfg["version"] == "v1" else
                os.path.join(os.path.dirname(cfg["loss_csv"]), f"loss_{cfg['version']}.csv"))
    os.makedirs(out_dir, exist_ok=True)
    print(f"version={tag} records={len(rows)} (first id {rows[0]['id']}, last id {rows[-1]['id']}) "
          f"epochs={cfg['epochs']} lr={cfg['learning_rate']} batch={cfg['batch_size']} seed={cfg['seed']}")

    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"], revision=cfg["base_model_revision"])
    tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(cfg["base_model"], revision=cfg["base_model_revision"],
                                                 torch_dtype=torch.float32)
    examples, truncated = build_examples(tokenizer, rows, cfg)
    print(f"examples={len(examples)} truncated={truncated} "
          f"mean_tokens={sum(len(i) for i, _ in examples) / len(examples):.1f}")

    steps_per_epoch = math.ceil(len(examples) / int(cfg["batch_size"]))
    total_steps = steps_per_epoch * int(cfg["epochs"])
    no_decay = ("bias", "layernorm", "layer_norm")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not any(x in n.lower() for x in no_decay)],
         "weight_decay": float(cfg["weight_decay"])},
        {"params": [p for n, p in model.named_parameters() if any(x in n.lower() for x in no_decay)],
         "weight_decay": 0.0},
    ]
    opt = torch.optim.AdamW(groups, lr=float(cfg["learning_rate"]))
    sched = get_linear_schedule_with_warmup(opt, int(float(cfg["warmup_ratio"]) * total_steps), total_steps)
    gen = torch.Generator().manual_seed(int(cfg["seed"]))

    history = []
    t_start = time.time()
    model.train()
    for epoch in range(1, int(cfg["epochs"]) + 1):
        t0 = time.time()
        loss_sum, tok_sum = 0.0, 0
        for input_ids, mask, labels in batches(examples, int(cfg["batch_size"]), tokenizer.pad_token_id, gen):
            out = model(input_ids=input_ids, attention_mask=mask, labels=labels)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(cfg["max_grad_norm"]))
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            n_tok = int((labels[:, 1:] != -100).sum())
            loss_sum += out.loss.item() * n_tok
            tok_sum += n_tok
        epoch_loss = loss_sum / max(tok_sum, 1)
        history.append((epoch, epoch_loss))
        print(f"epoch {epoch}/{cfg['epochs']}  loss {epoch_loss:.4f}  ({time.time() - t0:.0f}s)", flush=True)

    with open(loss_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["epoch", "train_loss"])
        for epoch_no, epoch_loss in history:
            w.writerow([epoch_no, f"{epoch_loss:.6f}"])

    model.save_pretrained(out_dir, safe_serialization=True)
    tokenizer.save_pretrained(out_dir)
    train_sha = None
    if os.path.exists(cfg.get("train_sha256_file", "")):
        with open(cfg["train_sha256_file"], encoding="utf-8") as f:
            train_sha = f.read().split()[0]
    info = {
        "version": tag,
        "base_model": cfg["base_model"],
        "base_model_revision": cfg["base_model_revision"],
        "method": "sequence-level knowledge distillation from phi3.5 (Ollama, temperature 0, seed 42)",
        "train_file": cfg["train_file"],
        "train_sha256": train_sha,
        "train_records": len(rows),
        "first_id": rows[0]["id"],
        "last_id": rows[-1]["id"],
        "seed": cfg["seed"],
        "learning_rate": cfg["learning_rate"],
        "batch_size": cfg["batch_size"],
        "epochs": cfg["epochs"],
        "max_seq_length": cfg["max_seq_length"],
        "prompt_template": cfg["prompt_template"],
        "final_train_loss": round(history[-1][1], 6),
        "training_seconds": round(time.time() - t_start, 1),
        "library_versions": versions,
    }
    with open(os.path.join(out_dir, "version.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(info, indent=2) + "\n")
    names = write_checksums(out_dir)
    print(f"saved {', '.join(names)} to {out_dir}; loss per epoch in {loss_csv}")
    print(f"model.sha256:\n{open(os.path.join(out_dir, 'model.sha256'), encoding='utf-8').read()}")


if __name__ == "__main__":
    main()
