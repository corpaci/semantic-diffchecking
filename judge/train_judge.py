#!/usr/bin/env python3
"""Finetune the ETP relation judge (Gemma-2-2B base + LoRA).

Runs on a single GPU (A100 recommended; fits a T4 with --load-4bit).
Reads the JSONL splits from build_pair_dataset.py. Label = single next token
after "Relation:", loss masked to that token only.

Smoke-test first (5 min):
  python3 train_judge.py --data data --dry-run

Full run:
  python3 train_judge.py --data data --out runs/judge-v0 \
      --push-to-hub yourname/etp-judge-gemma2-2b-v0

Env: HF_TOKEN must be set (Gemma is a gated model; accept the license on the
model page first). All hyperparameters are flags with sane defaults.
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="runs/judge-v0")
    ap.add_argument("--model", default="google/gemma-2-2b")
    ap.add_argument("--push-to-hub", default=None,
                    help="private HF repo id to upload adapter + merged model")
    ap.add_argument("--save-merged", action="store_true",
                    help="also write the merged bf16 model locally (~5 GB); "
                         "skip it and merge from the adapter later instead")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lora-layers", default="all",
                    help="all | early | middle | late | a-b (inclusive, 0-based)")
    ap.add_argument("--lora-modules", default="all", choices=["all", "attn", "mlp"])
    ap.add_argument("--micro-batch", type=int, default=32)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--eval-every", type=int, default=200)
    ap.add_argument("--eval-rows", type=int, default=0,
                    help="subsample the pairs_val/classes_val CURVE evals to N rows "
                         "(0 = full). The final test eval always uses the full split.")
    ap.add_argument("--keep-checkpoints", type=int, default=0,
                    help="save_total_limit; 0 = keep every checkpoint (needed for "
                         "the interp trajectory)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--load-4bit", action="store_true",
                    help="QLoRA mode for 16GB GPUs (T4); skip on A100")
    ap.add_argument("--dry-run", action="store_true",
                    help="200 train rows, 8 steps, no upload")
    args = ap.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              Trainer, TrainingArguments, set_seed)

    set_seed(args.seed)
    LABELS = ["equivalent", "weaker", "stronger", "incomparable"]

    tok = AutoTokenizer.from_pretrained(args.model)
    # Each label must be exactly one token after "Relation:" — verify, don't
    # assume: leading-space piece differs per tokenizer.
    label_ids = {}
    for lab in LABELS:
        ids = tok(" " + lab, add_special_tokens=False).input_ids
        label_ids[lab] = ids[0]
        if len(ids) > 1:
            print(f"note: ' {lab}' is {len(ids)} tokens; training on first, "
                  "eval compares first-token logits (still a valid 4-way head)")
    # Multi-token labels are fine ONLY while their first tokens stay distinct.
    # If two collided the head would silently degrade to 3-way and every number
    # downstream would be quiet garbage, so fail loudly instead of printing.
    if len(set(label_ids.values())) != len(LABELS):
        collisions = {tok.convert_ids_to_tokens([i])[0]: [l for l in LABELS if label_ids[l] == i]
                      for i in set(label_ids.values())}
        raise SystemExit(f"label first-tokens collide under {args.model}: {collisions}\n"
                         "pick single-token label synonyms before training.")

    def fmt(row):
        prompt = f"A: {row['text_a']}\nB: {row['text_b']}\nRelation:"
        ids = tok(prompt, add_special_tokens=True).input_ids
        input_ids = ids + [label_ids[row["label"]]]
        labels = [-100] * len(ids) + [label_ids[row["label"]]]
        return {"input_ids": input_ids, "labels": labels}

    files = {s: os.path.join(args.data, f"{s}.jsonl")
             for s in ["train", "pairs_val", "classes_val", "test"]}
    ds = load_dataset("json", data_files=files)
    if args.dry_run:
        ds["train"] = ds["train"].select(range(200))
        for s in ["pairs_val", "classes_val", "test"]:
            ds[s] = ds[s].select(range(100))
    keep = ["input_ids", "labels"]
    ds = ds.map(fmt, remove_columns=[c for c in ds["train"].column_names if c not in keep])
    # Curve evals are 62% as much forward compute as training at full size.
    # Subsampling them costs ~0.2pp of standard error and buys back ~35% of
    # wall clock; `test` is deliberately left whole for the headline number.
    curve = {s: ds[s] for s in ["pairs_val", "classes_val"]}
    if args.eval_rows and not args.dry_run:
        for s in curve:
            curve[s] = ds[s].select(range(min(args.eval_rows, len(ds[s]))))

    # Gemma-2 needs eager attention for its logit soft-capping; everything else
    # is faster on sdpa.
    attn = "eager" if "gemma-2" in args.model.lower() else "sdpa"
    model_kwargs = dict(torch_dtype=torch.bfloat16, attn_implementation=attn)
    if args.load_4bit:
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4")
    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)

    ATTN = ["q_proj", "k_proj", "v_proj", "o_proj"]
    MLP = ["gate_proj", "up_proj", "down_proj"]
    mods = {"all": ATTN + MLP, "attn": ATTN, "mlp": MLP}[args.lora_modules]
    missing = [m for m in mods if not any(m in n for n, _ in model.named_modules())]
    if missing:
        raise SystemExit(f"{args.model} has no modules named {missing}; "
                         "check the architecture's projection names.")

    n_layers = model.config.num_hidden_layers
    third = n_layers // 3
    spans = {"all": None,
             "early": list(range(0, third)),
             "middle": list(range(third, 2 * third)),
             "late": list(range(2 * third, n_layers))}
    if args.lora_layers in spans:
        layers = spans[args.lora_layers]
    else:
        lo, hi = (int(x) for x in args.lora_layers.split("-"))
        layers = list(range(lo, hi + 1))
    print(f"LoRA: r={args.rank} modules={args.lora_modules} "
          f"layers={args.lora_layers} -> {'all ' + str(n_layers) if layers is None else layers}")

    lora = LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
                      target_modules=mods, task_type="CAUSAL_LM",
                      layers_to_transform=layers,
                      layers_pattern="layers" if layers is not None else None)
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def collate(batch):
        maxlen = max(len(b["input_ids"]) for b in batch)
        pad = tok.pad_token_id or tok.eos_token_id
        input_ids, labels, attn = [], [], []
        for b in batch:
            k = maxlen - len(b["input_ids"])
            input_ids.append(b["input_ids"] + [pad] * k)
            labels.append(b["labels"] + [-100] * k)
            attn.append([1] * len(b["input_ids"]) + [0] * k)
        return {"input_ids": torch.tensor(input_ids),
                "labels": torch.tensor(labels),
                "attention_mask": torch.tensor(attn)}

    id_list = [label_ids[lab] for lab in LABELS]

    def compute_metrics(pred):
        import numpy as np
        logits, labels = pred
        # logits arrive already argmaxed over the label-token position via
        # preprocess_logits_for_metrics below: shape (n, 4) restricted scores
        rows, gold = [], []
        for lg, lb in zip(logits, labels):
            pos = np.where(lb != -100)[0]
            if len(pos) == 0:
                continue
            rows.append(lg)
            gold.append(id_list.index(lb[pos[0]]))
        rows = np.array(rows); gold = np.array(gold)
        pred4 = rows.argmax(-1)
        acc = float((pred4 == gold).mean())
        per = {f"acc_{LABELS[i]}": float((pred4[gold == i] == i).mean())
               for i in range(4) if (gold == i).any()}
        return {"acc": acc, **per}

    def preprocess_logits(logits, labels):
        # keep only the 4 label-token logits at the label position
        import torch as t
        pos = (labels != -100).float().argmax(-1) - 1  # logits index preceding label
        idx = pos.clamp(min=0).long()
        gathered = logits[t.arange(logits.size(0)), idx][:, id_list]
        return gathered

    steps = 8 if args.dry_run else args.max_steps
    targs = TrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=args.micro_batch,
        per_device_eval_batch_size=args.micro_batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, lr_scheduler_type="cosine",
        warmup_ratio=0.03, max_steps=steps, logging_steps=10,
        eval_strategy="steps", eval_steps=args.eval_every if not args.dry_run else 4,
        save_steps=args.eval_every,
        save_total_limit=args.keep_checkpoints or None,
        bf16=True, report_to="none", seed=args.seed,
        dataloader_num_workers=2, remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model, args=targs,
        train_dataset=ds["train"],
        eval_dataset={"pairs": curve["pairs_val"], "classes": curve["classes_val"]},
        data_collator=collate, compute_metrics=compute_metrics,
        preprocess_logits_for_metrics=preprocess_logits,
    )
    trainer.train()

    print("\nFinal test-split eval (held-out classes):")
    test_metrics = trainer.evaluate(ds["test"], metric_key_prefix="test")
    print(test_metrics)

    # Adapter + tokenizer are the durable artifact: ~80 MB, and the merged
    # model is reconstructible from them plus the base weights at any time.
    adapter_dir = os.path.join(args.out, "adapter-final")
    trainer.save_model(adapter_dir)
    tok.save_pretrained(adapter_dir)
    print(f"saved adapter + tokenizer to {adapter_dir}")

    with open(os.path.join(args.out, "run_config.json"), "w") as f:
        json.dump(vars(args), f, indent=2, default=str)
    with open(os.path.join(args.out, "final_metrics.json"), "w") as f:
        json.dump(test_metrics, f, indent=2, default=str)

    if args.save_merged and not args.dry_run:
        merged_dir = os.path.join(args.out, "merged-bf16")
        model.merge_and_unload().save_pretrained(merged_dir)
        tok.save_pretrained(merged_dir)
        print(f"saved merged bf16 model to {merged_dir} (~5 GB)")

    if args.push_to_hub and not args.dry_run:
        model.push_to_hub(args.push_to_hub, private=True)
        tok.push_to_hub(args.push_to_hub, private=True)
        merged = model.merge_and_unload()
        merged.push_to_hub(args.push_to_hub + "-merged", private=True)
        print("pushed adapter and merged model to the Hub")


if __name__ == "__main__":
    main()
