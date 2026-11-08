"""Shared inference code for the command parser (used by the service and by training/predict.py).

The student was trained on examples of the form
    Command: <the command>
    JSON: <the teacher's JSON reply><eos>
so at inference time we feed "Command: <text>\nJSON:" and decode greedily until the
end-of-sequence token, a newline, or MAX_NEW_TOKENS.
"""
import os

PROMPT_TEMPLATE = "Command: {text}\nJSON:"


def build_prompt(text):
    return PROMPT_TEMPLATE.format(text=" ".join(str(text).split()))


def cgroup_cpus(default=1):
    """Number of CPUs this container may use (from the cgroup CPU quota), at least 1."""
    try:
        with open("/sys/fs/cgroup/cpu.max", encoding="utf-8") as f:  # cgroup v2
            quota, period = f.read().split()[:2]
        if quota != "max":
            return max(1, int(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", encoding="utf-8") as f:  # cgroup v1
            quota = int(f.read())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", encoding="utf-8") as f:
            period = int(f.read())
        if quota > 0:
            return max(1, quota // period)
    except (OSError, ValueError):
        pass
    return max(1, os.cpu_count() or default)


class CommandParser:
    def __init__(self, model_dir, threads=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        torch.set_num_threads(threads or cgroup_cpus())
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=torch.float32)
        self.model.eval()
        self.eos_id = self.tokenizer.eos_token_id
        # token ids whose text contains a newline: generation stops at the end of the line
        self.newline_ids = {i for t, i in self.tokenizer.get_vocab().items()
                            if "\n" in self.tokenizer.convert_tokens_to_string([t])}

    def generate(self, text, max_new_tokens=64):
        """Greedy decoding; returns the raw generated text (without the prompt)."""
        from transformers import DynamicCache

        torch = self.torch
        ids = self.tokenizer(build_prompt(text), return_tensors="pt").input_ids
        out = []
        past = DynamicCache()
        with torch.inference_mode():
            inp = ids
            for _ in range(int(max_new_tokens)):
                res = self.model(input_ids=inp, past_key_values=past, use_cache=True)
                past = res.past_key_values
                nxt = int(res.logits[0, -1].argmax())
                if nxt == self.eos_id or nxt in self.newline_ids:
                    break
                out.append(nxt)
                inp = torch.tensor([[nxt]])
        return self.tokenizer.decode(out, skip_special_tokens=True).strip()
