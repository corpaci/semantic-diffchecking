#!/usr/bin/env python3
"""ETP relation judge — library and command-line interface.

Classifies the logical relation between two equational laws:

    equivalent | weaker | stronger | incomparable

The label describes B relative to A, matching the oracle's convention
(`weaker` = B drops constraints). Scoring is a single forward pass whose
logits are restricted to the four label tokens, so the judge cannot emit an
invalid answer and every prediction carries a calibrated probability.

CLI
---
    judge.py compare "x * y = y * x" "a * b = b * a"
    judge.py compare -A "..." -B "..." --json
    judge.py batch pairs.jsonl --out scored.jsonl
    judge.py rank intended.txt candidates.txt

Library
-------
    from judge import Judge
    j = Judge("adapters/judge-v0")
    j.compare("x * y = y * x", "a * b = b * a")     # -> Verdict
    j.probs([(a, b), ...])                          # -> (n, 4) ndarray

No GPU required. A single comparison takes a couple of seconds on CPU;
CUDA and Apple-Silicon MPS are used automatically when present.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict

LABELS = ("equivalent", "weaker", "stronger", "incomparable")
DEFAULT_BASE = "google/gemma-2-2b"


@dataclass
class Verdict:
    label: str
    confidence: float
    probs: dict          # label -> probability
    text_a: str
    text_b: str

    def __str__(self) -> str:
        return f"{self.label} ({self.confidence:.3f})"


class Judge:
    """A loaded relation judge. Construct once, score many times."""

    def __init__(self, adapter: str, base: str | None = None,
                 device: str | None = None, dtype: str = "bfloat16"):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        if device is None:
            device = ("cuda" if torch.cuda.is_available()
                      else "mps" if torch.backends.mps.is_available() else "cpu")
        self.device = device
        # bf16 is unreliable on CPU; fall back to fp32 there.
        td = getattr(torch, dtype) if device != "cpu" else torch.float32

        # The adapter records which base model it was trained against, so the
        # caller does not have to remember. An explicit --base still wins.
        if base is None:
            cfg = os.path.join(adapter, "adapter_config.json")
            if os.path.isfile(cfg):
                with open(cfg) as f:
                    base = json.load(f).get("base_model_name_or_path")
            base = base or DEFAULT_BASE
        self.base_name = base

        # The tokenizer is saved beside the adapter; fall back to the base.
        try:
            self.tok = AutoTokenizer.from_pretrained(adapter)
        except Exception:
            self.tok = AutoTokenizer.from_pretrained(base)

        self.label_ids = [self.tok(" " + l, add_special_tokens=False).input_ids[0]
                          for l in LABELS]
        if len(set(self.label_ids)) != len(LABELS):
            raise SystemExit(
                f"label first-tokens collide under {base}; the 4-way head would "
                "silently degrade. Pick single-token label synonyms and retrain.")

        # Gemma-2 requires eager attention for its logit soft-capping.
        attn = "eager" if "gemma-2" in base.lower() else "sdpa"
        try:
            model = AutoModelForCausalLM.from_pretrained(
                base, dtype=td, attn_implementation=attn)
        except TypeError:                      # transformers < 5 spells it torch_dtype
            model = AutoModelForCausalLM.from_pretrained(
                base, torch_dtype=td, attn_implementation=attn)
        self.model = PeftModel.from_pretrained(model, adapter).to(device).eval()

    @staticmethod
    def prompt(text_a: str, text_b: str) -> str:
        return f"A: {text_a}\nB: {text_b}\nRelation:"

    def probs(self, pairs, batch_size: int = 32):
        """pairs: iterable of (text_a, text_b). Returns an (n, 4) float array."""
        torch = self.torch
        pairs = list(pairs)
        out = []
        with torch.no_grad():
            for i in range(0, len(pairs), batch_size):
                chunk = pairs[i:i + batch_size]
                enc = [self.tok(self.prompt(a, b), add_special_tokens=True).input_ids
                       for a, b in chunk]
                m = max(len(e) for e in enc)
                pad = self.tok.pad_token_id
                if pad is None:
                    pad = self.tok.eos_token_id
                ids = torch.tensor([e + [pad] * (m - len(e)) for e in enc],
                                   device=self.device)
                att = torch.tensor([[1] * len(e) + [0] * (m - len(e)) for e in enc],
                                   device=self.device)
                last = torch.tensor([len(e) - 1 for e in enc], device=self.device)
                lg = self.model(input_ids=ids, attention_mask=att).logits
                # Take the logits at each row's true final position, then keep
                # only the four label tokens -- this is what makes an invalid
                # answer impossible rather than merely unlikely.
                lg = lg[torch.arange(lg.size(0), device=self.device), last][:, self.label_ids]
                out.append(torch.softmax(lg.float(), -1).cpu())
        return torch.cat(out).numpy() if out else None

    def compare(self, text_a: str, text_b: str) -> Verdict:
        p = self.probs([(text_a, text_b)])[0]
        k = int(p.argmax())
        return Verdict(label=LABELS[k], confidence=float(p[k]),
                       probs={l: float(v) for l, v in zip(LABELS, p)},
                       text_a=text_a, text_b=text_b)

    def rank(self, intended: str, candidates):
        """Order candidates by P(equivalent to `intended`), best first.

        This is the operation best-of-n selection performs, so it is the one
        that matters when the judge is used as a checker under optimisation
        pressure -- not top-1 accuracy on independent pairs.
        """
        cands = list(candidates)
        p = self.probs([(intended, c) for c in cands])
        scored = [(c, float(p[i][0]), LABELS[int(p[i].argmax())])
                  for i, c in enumerate(cands)]
        return sorted(scored, key=lambda t: -t[1])


# --------------------------------------------------------------------------- CLI

def _add_model_args(p):
    p.add_argument("--adapter", default=os.environ.get("JUDGE_ADAPTER"),
                   help="path to a trained adapter dir (or set JUDGE_ADAPTER)")
    p.add_argument("--base", default=None,
                   help="base model id; read from adapter_config.json if omitted")
    p.add_argument("--device", default=None, help="cuda | mps | cpu (auto by default)")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="judge", description="Classify the relation between two equational laws.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare", help="score a single pair")
    c.add_argument("a", nargs="?"); c.add_argument("b", nargs="?")
    c.add_argument("-A", dest="a_flag"); c.add_argument("-B", dest="b_flag")
    c.add_argument("--json", action="store_true")
    _add_model_args(c)

    b = sub.add_parser("batch", help="score a JSONL file of {text_a, text_b} rows")
    b.add_argument("infile")
    b.add_argument("--out", default=None, help="write JSONL here (default: stdout)")
    b.add_argument("--batch-size", type=int, default=32)
    _add_model_args(b)

    r = sub.add_parser("rank", help="rank candidates by P(equivalent to intended)")
    r.add_argument("intended", help="the intended law, or a file containing it")
    r.add_argument("candidates", help="file with one candidate per line")
    r.add_argument("--json", action="store_true")
    _add_model_args(r)

    args = ap.parse_args()
    if not args.adapter:
        ap.error("no adapter given; pass --adapter PATH or set JUDGE_ADAPTER")

    j = Judge(args.adapter, base=args.base, device=args.device)

    if args.cmd == "compare":
        a = args.a_flag or args.a
        b_ = args.b_flag or args.b
        if not a or not b_:
            ap.error("need two equations: judge.py compare 'A' 'B'")
        v = j.compare(a, b_)
        if args.json:
            print(json.dumps(asdict(v), indent=2))
        else:
            print(f"A: {a}\nB: {b_}\n\n  {v.label}   (confidence {v.confidence:.3f})\n")
            for lab, p in sorted(v.probs.items(), key=lambda t: -t[1]):
                bar = "#" * int(round(p * 40))
                print(f"  {lab:14s} {p:6.3f}  {bar}")

    elif args.cmd == "batch":
        rows = [json.loads(l) for l in open(args.infile, encoding="utf-8") if l.strip()]
        p = j.probs([(r["text_a"], r["text_b"]) for r in rows], batch_size=args.batch_size)
        sink = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
        agree = total = 0
        for row, pr in zip(rows, p):
            k = int(pr.argmax())
            row["pred"] = LABELS[k]
            row["confidence"] = float(pr[k])
            row["probs"] = {l: float(v) for l, v in zip(LABELS, pr)}
            if "label" in row:                       # gold present -> score it
                total += 1
                agree += row["label"] == row["pred"]
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        if args.out:
            sink.close()
        if total:
            print(f"accuracy {agree}/{total} = {agree / total:.4f}", file=sys.stderr)

    elif args.cmd == "rank":
        intended = (open(args.intended, encoding="utf-8").read().strip()
                    if os.path.isfile(args.intended) else args.intended)
        cands = [l.strip() for l in open(args.candidates, encoding="utf-8") if l.strip()]
        ranked = j.rank(intended, cands)
        if args.json:
            print(json.dumps([{"candidate": c, "p_equivalent": p, "pred": lab}
                              for c, p, lab in ranked], indent=2))
        else:
            print(f"intended: {intended}\n")
            for i, (c, p, lab) in enumerate(ranked, 1):
                print(f"  {i:3d}. p(equiv)={p:.4f}  [{lab:12s}]  {c}")


if __name__ == "__main__":
    main()
