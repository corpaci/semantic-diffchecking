#!/usr/bin/env python3
"""One config file describes a whole run, and the run records the config back.

Before this, a run was defined by a command line: which flags were passed to
`build_pair_dataset.py`, then which flags were passed to `train_judge.py`, then
whatever was typed to evaluate it. Nothing tied the three together, and a
finished adapter did not carry the sampler settings that produced its data. Two
of this project's real bugs were of exactly that shape -- a flag that silently
did nothing, and a flag that did the opposite of its name -- and neither was
visible from the artifacts afterwards.

So: every stage reads one file, and the resolved config is written into the run
directory as `resolved_config.yaml`. If you have the run, you have the recipe.

Sections
--------
    data    which pairs get built, and how they are sampled
    render  how an equation is written down (see representations.py)
    prompt  the exact string the model is shown
    model   base model and LoRA shape
    train   optimisation settings
    eval    what gets measured afterwards

Anything absent falls back to the defaults below, which reproduce judge-v0.

Usage
-----
    from config import load
    cfg = load("configs/baseline.yaml")
    cfg.render.kind        # "infix"
    cfg.dump(run_dir)      # writes resolved_config.yaml
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field, asdict, fields

DEFAULTS = {
    "name": "unnamed",
    "seed": 0,
    "data": {
        "sampler": "original",        # existing label-balanced sampler
        "out_dir": "judge/data",
        # original sampler
        "per_class_train": 60000,
        "per_class_eval": 2000,
        # split, shared
        "pin_size": 50,
        "test_frac": 0.15,
        "val_frac": 0.10,
    },
    "render": {
        "kind": "infix",              # infix | function_call | lean | latex | python
        "op": None,                   # None -> draw at random per row
        "rename": True,
        "flip": True,
    },
    "prompt": {
        # {a} and {b} are the two rendered equations. The trailing text is what
        # the answer token follows, so it must not end in a space: the space
        # belongs to the label token itself (" equivalent", not "equivalent").
        "template": "A: {a}\nB: {b}\nRelation:",
        "labels": ["equivalent", "weaker", "stronger", "incomparable"],
    },
    "model": {
        "base": "google/gemma-2-2b",
        "lora_rank": 16,
        "lora_layers": "all",         # all | early | middle | late
        "lora_modules": "all",        # all | attn | mlp
    },
    "train": {
        "lr": 1e-4,
        "micro_batch": 32,
        "grad_accum": 4,              # micro_batch * grad_accum = 128, keep it
        "max_steps": 2000,
        "eval_every": 200,
        "eval_rows": 2000,
        "keep_checkpoints": 0,        # 0 = keep every one
        "out_dir": "judge/runs/unnamed",
    },
    "eval": {
        "splits": ["pairs_val", "classes_val", "test"],
        "metrics": ["accuracy", "false_equivalence", "missed_equivalence",
                    "per_label", "per_tier"],
    },
}


class Section(dict):
    """A dict that also answers to attribute access, so cfg.render.kind works."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(
                f"no config key {k!r} in this section; have {sorted(self)}") from e


@dataclass
class Config:
    name: str
    seed: int
    data: Section
    render: Section
    prompt: Section
    model: Section
    train: Section
    eval: Section
    source_path: str = ""

    def dump(self, run_dir: str) -> str:
        """Write the fully resolved config beside the run it produced."""
        os.makedirs(run_dir, exist_ok=True)
        p = os.path.join(run_dir, "resolved_config.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write(_to_yaml(self.as_dict()))
        return p

    def as_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "source_path"}
        return {k: (dict(v) if isinstance(v, Section) else v) for k, v in d.items()}

    def prompt_for(self, a: str, b: str) -> str:
        return self.prompt.template.format(a=a, b=b)


def _deep_merge(base: dict, over: dict, path: str = "") -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        here = f"{path}.{k}" if path else k
        if k not in out:
            raise KeyError(f"unknown config key {here!r}. "
                           f"Valid keys here: {sorted(out)}")
        if isinstance(v, dict) and isinstance(out[k], dict):
            out[k] = _deep_merge(out[k], v, here)
        else:
            out[k] = v
    return out


def _to_yaml(d: dict, indent: int = 0) -> str:
    pad = "  " * indent
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(_to_yaml(v, indent + 1))
        elif isinstance(v, list):
            lines.append(f"{pad}{k}: {json.dumps(v)}")
        elif isinstance(v, str):
            lines.append(f"{pad}{k}: {json.dumps(v)}")
        elif v is None:
            lines.append(f"{pad}{k}: null")
        else:
            lines.append(f"{pad}{k}: {v}")
    return "\n".join(l for l in lines if l)


def load(path: str) -> Config:
    """Read a config, merge it over the defaults, and check it makes sense."""
    try:
        import yaml
    except ImportError:
        with open(path, encoding="utf-8") as source:
            raw = json.load(source)
    else:
        with open(path, encoding="utf-8") as source:
            raw = yaml.safe_load(source) or {}
    merged = _deep_merge(DEFAULTS, raw)
    cfg = Config(
        name=merged["name"], seed=merged["seed"],
        data=Section(merged["data"]), render=Section(merged["render"]),
        prompt=Section(merged["prompt"]), model=Section(merged["model"]),
        train=Section(merged["train"]), eval=Section(merged["eval"]),
        source_path=os.path.abspath(path))
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    """Fail loudly on the mistakes that would otherwise pass silently."""
    if __package__:
        from .representations import RENDERERS
    else:
        from representations import RENDERERS

    if cfg.render.kind not in RENDERERS:
        raise SystemExit(f"render.kind {cfg.render.kind!r} unknown; "
                         f"have {sorted(RENDERERS)}")
    if cfg.data.sampler != "original":
        raise SystemExit(f"data.sampler {cfg.data.sampler!r} unknown")
    supported_metrics = set(DEFAULTS["eval"]["metrics"])
    if not cfg.eval.metrics or set(cfg.eval.metrics) - supported_metrics:
        raise ValueError(f"eval.metrics must select from {sorted(supported_metrics)}")
    if not cfg.eval.splits or set(cfg.eval.splits) - {"pairs_val", "classes_val", "test"}:
        raise ValueError("eval.splits must select pairs_val, classes_val, or test")
    for key in ("rename", "flip"):
        if not isinstance(cfg.render[key], bool):
            raise ValueError(f"render.{key} must be a boolean")
    for section, keys in ((cfg.data, ("per_class_train", "per_class_eval", "pin_size")),
                          (cfg.train, ("micro_batch", "grad_accum", "max_steps", "eval_every", "eval_rows"))):
        for key in keys:
            if type(section[key]) is not int or section[key] < 1:
                raise ValueError(f"{key} must be a positive integer")
    if type(cfg.train.keep_checkpoints) is not int or cfg.train.keep_checkpoints < 0:
        raise ValueError("train.keep_checkpoints must be a non-negative integer")
    if not (0 < cfg.data.test_frac < 1 and 0 < cfg.data.val_frac < 1
            and cfg.data.test_frac + cfg.data.val_frac < 1):
        raise ValueError("test_frac and val_frac must be positive and sum to less than one")

    t = cfg.prompt.template
    for tok in ("{a}", "{b}"):
        if tok not in t:
            raise SystemExit(f"prompt.template must contain {tok}")
    if t.endswith(" "):
        raise SystemExit(
            "prompt.template ends in a space. The label token carries its own "
            "leading space (' equivalent'), so a trailing space here shifts "
            "the target token and the run trains on the wrong thing.")
    try:
        t.format(a="A", b="B")
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError("prompt.template must format using only {a} and {b}") from exc
    if cfg.prompt.labels != DEFAULTS["prompt"]["labels"]:
        raise ValueError("prompt.labels must preserve the four trained label identifiers and their order")

    eff = cfg.train.micro_batch * cfg.train.grad_accum
    if eff != 128:
        print(f"warning: micro_batch x grad_accum = {eff}, not 128. Runs are "
              "only comparable to the published ones at an effective batch "
              "of 128.")


if __name__ == "__main__":
    import sys
    c = load(sys.argv[1])
    print(_to_yaml(c.as_dict()))
    print(f"\nexample prompt:\n{c.prompt_for('x * y = y * x', 'a * b = b * a')}")
