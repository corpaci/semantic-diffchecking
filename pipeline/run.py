#!/usr/bin/env python3
"""Run a stage, or all of them, from one config file.

    python3 pipeline/run.py --config configs/rep-lean.yaml --stage all
    python3 pipeline/run.py --config configs/rep-lean.yaml --stage data
    python3 pipeline/run.py --config configs/rep-lean.yaml --stage train
    python3 pipeline/run.py --config configs/rep-lean.yaml --stage eval

Stages
------
    data    build the four JSONL splits described by cfg.data and cfg.render
    train   finetune cfg.model on them with cfg.train
    eval    score configured splits and write the requested metrics

Each stage writes into the run directory, and `resolved_config.yaml` goes there
first, so the recipe sits beside the artifact rather than in someone's shell
history.

`--dry-run` prints what each stage would do, builds nothing and trains nothing.
Use it to check a config before spending on a GPU.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(HERE)
if __package__:
    from .config import Config, load, validate
    from .metrics import summarize
else:
    from config import Config, load, validate
    from metrics import summarize


def _abs(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(WORK, p)


def stage_data(cfg, dry: bool) -> None:
    """Build the dataset. Delegates to build_pair_dataset.py rather than
    reimplementing it, so the validated sampler stays the only sampler."""
    out = _abs(cfg.data.out_dir)
    cmd = [sys.executable, _abs("judge/build_pair_dataset.py"),
           "--out", out, "--seed", str(cfg.seed),
           "--pin-size", str(cfg.data.pin_size),
           "--test-frac", str(cfg.data.test_frac),
           "--val-frac", str(cfg.data.val_frac)]
    cmd += ["--per-class-train", str(cfg.data.per_class_train),
            "--per-class-eval", str(cfg.data.per_class_eval)]

    env = dict(os.environ)
    # The renderer is passed through the environment because
    # build_pair_dataset.augment() reads it there; anything other than "infix"
    # changes every row it writes.
    env["SDC_RENDER_KIND"] = cfg.render.kind
    env["SDC_RENDER_RENAME"] = str(bool(cfg.render.rename))
    env["SDC_RENDER_FLIP"] = str(bool(cfg.render.flip))
    env.pop("SDC_RENDER_OP", None)
    if cfg.render.op:
        env["SDC_RENDER_OP"] = str(cfg.render.op)

    print(f"[data] representation={cfg.render.kind} sampler={cfg.data.sampler}")
    print("[data] " + " ".join(cmd))
    if dry:
        return
    recipe = {"data": dict(cfg.data), "render": dict(cfg.render), "seed": cfg.seed}
    marker = os.path.join(out, "pipeline_data_config.json")
    if os.path.isdir(out) and os.listdir(out):
        if os.path.isfile(marker):
            with open(marker, encoding="utf-8") as source:
                matches = json.load(source) == recipe
            if matches and all(os.path.isfile(os.path.join(out, f"{split}.jsonl"))
                               for split in ("train", "pairs_val", "classes_val", "test")):
                print(f"[data] reusing the matching dataset at {out}")
                return
        raise ValueError(f"{out} contains data with a missing or different recipe; "
                         "choose a fresh data.out_dir or run only train/eval on existing data")
    subprocess.run(cmd, check=True, env=env)
    with open(marker, "w", encoding="utf-8") as sink:
        json.dump(recipe, sink, indent=2)


def stage_train(cfg, dry: bool) -> None:
    out = _abs(cfg.train.out_dir)
    if not dry and os.path.exists(os.path.join(out, "adapter-final")):
        raise SystemExit(f"{out}/adapter-final exists. Refusing to overwrite a "
                         "trained adapter; move it or change train.out_dir.")
    cmd = [sys.executable, _abs("judge/train_judge.py"),
           "--data", _abs(cfg.data.out_dir), "--out", out,
           "--model", cfg.model.base, "--rank", str(cfg.model.lora_rank),
           "--lora-layers", cfg.model.lora_layers,
           "--lora-modules", cfg.model.lora_modules,
           "--lr", str(cfg.train.lr),
           "--micro-batch", str(cfg.train.micro_batch),
           "--grad-accum", str(cfg.train.grad_accum),
           "--max-steps", str(cfg.train.max_steps),
           "--eval-every", str(cfg.train.eval_every),
           "--eval-rows", str(cfg.train.eval_rows),
           "--keep-checkpoints", str(cfg.train.keep_checkpoints),
           "--seed", str(cfg.seed)]
    env = dict(os.environ)
    env["SDC_PROMPT_TEMPLATE"] = cfg.prompt.template
    print(f"[train] {cfg.model.base}  rank={cfg.model.lora_rank} "
          f"batch={cfg.train.micro_batch}x{cfg.train.grad_accum}")
    print("[train] " + " ".join(cmd))
    if dry:
        return
    subprocess.run(cmd, check=True, env=env)


def stage_eval(cfg, dry: bool) -> None:
    out = _abs(cfg.train.out_dir)
    adapter = os.path.join(out, "adapter-final")
    if not dry and not os.path.isdir(adapter):
        raise SystemExit(f"no adapter at {adapter}; run --stage train first")
    print(f"[eval] splits={cfg.eval.splits} metrics={cfg.eval.metrics}")
    if dry:
        return
    results = {}
    for split in cfg.eval.splits:
        f = os.path.join(_abs(cfg.data.out_dir), f"{split}.jsonl")
        subprocess.run(
            [sys.executable, _abs("judge/judge.py"),
             "batch", f, "--adapter", adapter, "--batch-size", "64",
             "--out", os.path.join(out, f"scored_{split}.jsonl")],
            capture_output=True, text=True, check=True)
        scored = os.path.join(out, f"scored_{split}.jsonl")
        with open(scored, encoding="utf-8") as source:
            rows = [json.loads(line) for line in source if line.strip()]
        results[split] = summarize(rows, cfg.eval.metrics)
        print(f"[eval] {split}: {results[split]}")
    with open(os.path.join(out, "eval_summary.json"), "w") as fh:
        json.dump(results, fh, indent=2)


def run(config: str | os.PathLike | Config, *, stage: str = "all",
        dry_run: bool = False) -> dict:
    """Run configured stages from Python and return their artifact locations.

    ``config`` is a YAML/JSON path or a Config returned by ``config.load``.
    Relative artifact paths resolve against this workspace, as in the CLI.
    A dry run validates and prints commands without writing or launching jobs.
    Stage failures propagate to the caller; later stages do not run.
    """
    if stage not in ("all", "data", "train", "eval"):
        raise ValueError("stage must be all, data, train, or eval")
    cfg = config if isinstance(config, Config) else load(os.fspath(config))
    validate(cfg)
    run_dir = _abs(cfg.train.out_dir)
    stages = ["data", "train", "eval"] if stage == "all" else [stage]
    if not dry_run and "train" in stages and os.path.exists(os.path.join(run_dir, "adapter-final")):
        raise FileExistsError(f"{run_dir}/adapter-final exists; choose a new train.out_dir")
    source = cfg.source_path or "in-memory config"
    print(f"=== {cfg.name}   (from {source})")
    if not dry_run:
        print("wrote", cfg.dump(run_dir))

    t0 = time.time()
    for name in stages:
        print(f"\n--- stage: {name}")
        {"data": stage_data, "train": stage_train, "eval": stage_eval}[name](cfg, dry_run)
    print(f"\ndone in {(time.time()-t0)/60:.1f} min")
    return {
        "name": cfg.name, "stages": stages, "dry_run": dry_run,
        "run_dir": run_dir,
        "data_dir": _abs(cfg.data.out_dir),
        "adapter_dir": os.path.join(run_dir, "adapter-final"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--stage", default="all",
                    choices=["all", "data", "train", "eval"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    run(args.config, stage=args.stage, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
