# `infra/` — optional GPU-rental helpers

**Nothing here is required.** Using the judge needs no GPU, and retraining works
on any CUDA box via `train_judge.py` directly. These scripts exist only because
the runs behind `judge/README.md` were done on rented GPUs, and reproducing them
exactly is easier with the same glue.

If you have your own GPU, ignore this directory.

---

## `launch_thunder.sh`

Laptop-side wrapper around the [Thunder Compute](https://www.thundercompute.com)
CLI (`tnr`), which rents per-minute GPUs.

```bash
DISK=100 ./launch_thunder.sh up          # create an instance
./launch_thunder.sh push <id>            # upload code + data
./launch_thunder.sh token <id>           # copy the local HF token up
./launch_thunder.sh pull <id>            # bring runs/ back
./launch_thunder.sh down <id>            # delete (this is what stops billing)
```

Override `GPU` (`a6000` / `a100` / `h100` / `l40`), `VCPUS`, `DISK`, `TEMPLATE`
by environment variable.

Two behaviours worth knowing, both learned the hard way:

- **`push` stashes `runs/` for the duration of the sync**, with a trap to restore
  it even on failure. Without this, rsync uploads tens of GB of checkpoints the
  instance never needs — and worse, can overwrite a log file a live training job
  is writing to.
- **Billing stops on `delete`, not on disconnect.** An idle instance still
  charges. `tnr status` should read `No instances found` when you are done.

---

## What was deliberately left out

Three scripts used during the original runs are **not** in the repo, because they
are operational scaffolding rather than research artifacts. Recreating them is a
few lines if you want them; what mattered is documented below.

### `remote_run.sh` — instance-side driver

Ran on the GPU box and wrapped four things:

1. **`setup`** — `pip install "transformers>=4.44,<5" peft datasets accelerate`.
   The upper pin matters: transformers 5.x renamed `torch_dtype=` to `dtype=`,
   which breaks `train_judge.py`'s model loading.
2. **Preflight** — assert CUDA is visible, assert the gated Gemma download works,
   and assert all four label words are single distinct tokens under the
   tokenizer. That last check is now an assertion inside `train_judge.py`, since
   a first-token collision would silently degrade the 4-way head to 3-way.
3. **`train`** — launch under `nohup` so a dropped SSH session does not kill a
   multi-hour run.
4. **`status`** — parse the `\r`-laden progress log into something readable.

### `watch.sh` / `watch-llama.sh` — progress monitors

Polled the instance and emitted one line per state change: run started, run
finished with `test_acc`, OOM, traceback, or process death. Useful while
babysitting a six-hour sweep; useless afterwards.

The one design note worth keeping: a monitor that greps only for the success
marker stays **silent** through a crashloop, and silence is indistinguishable
from "still training". Any replacement should match every terminal state, not
just the happy path.

---

## Reproducing the runs without Thunder

Nothing above is load-bearing. On any machine with a suitable GPU:

```bash
python3 build_pair_dataset.py --out data/
python3 train_judge.py --data data --out runs/judge-v0 \
    --micro-batch 64 --grad-accum 2 --eval-rows 2000 --keep-checkpoints 0
```

See the memory table in `judge/README.md` for VRAM requirements per model and
micro-batch — `≥ 40 GB` is the practical floor at micro-batch 64.
