"""The reconstruction sweep: one representation of one law per call, 9 models.

Reads `sample.json` and `prompts.json`, assembles each prompt from the
representation's template and the catalogue rendering, and records the raw
response. No grading here — `grade.py` does that from the stored text, so the
oracle's verdicts can be recomputed without spending money again.

## Resume

Every row is appended to `<representation>/raw-<slug>.jsonl` and flushed
immediately, so an interruption loses at most the calls in flight. Each file
opens with an identity header pinning the model, the prompt template's sha256,
the sample seed, `max_tokens`, temperature, and the reasoning argument; a file
whose header disagrees with the current configuration is refused rather than
silently mixed. On restart the completed `(representation, node, k)` keys are
read back and skipped.

## Randomized call order

The 14,400 tasks per model are shuffled with a fixed per-model seed. Running
representation by representation would mean an interruption leaves complete data
for some representations and none for others; shuffled, any partial run is
balanced across all 18 and still analyzable.

## The repeat arm

150 of the 500 equations are sampled three times (`k` = 0, 1, 2) with seed
`SEED + k`, so the repeats measure real sampling variability under the same
configuration rather than returning a cached identical answer. The other 350 are
k=0 only.

    python3 run_experiment.py --smoke 2        # 2 equations, all reps/models
    python3 run_experiment.py                  # the full sweep
    python3 run_experiment.py --status         # read-only progress
    python3 run_experiment.py --models gpt-5.2 # one model
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "translate" / "nl"))
sys.path.insert(0, str(REPO / "oracle"))

import openrouter  # noqa: E402

SEED = 20260830
TASK_SEED = 771
MAX_TOKENS = 900
TEMPERATURE = 0
TRANSIENT = frozenset({408, 409, 429, 500, 502, 503, 504})
BACKOFF_ATTEMPTS = 5
BACKOFF_BASE_S = 4.0

MODELS = [
    dict(tier="small", id="mistralai/mistral-small-3.2-24b-instruct",
         slug="mistral-small-3.2-24b", reasoning=None, temp=True, seed=True, conc=12),
    dict(tier="small", id="qwen/qwen3-30b-a3b-instruct-2507",
         slug="qwen3-30b-a3b", reasoning=None, temp=True, seed=True, conc=12),
    dict(tier="small", id="microsoft/phi-4",
         slug="phi-4", reasoning=None, temp=True, seed=True, conc=16),
    dict(tier="medium", id="google/gemini-2.5-flash",
         slug="gemini-2.5-flash", reasoning={"enabled": False}, temp=True, seed=True, conc=12),
    dict(tier="medium", id="meta-llama/llama-4-maverick",
         slug="llama-4-maverick", reasoning=None, temp=True, seed=True, conc=24),
    dict(tier="medium", id="x-ai/grok-4.20",
         slug="grok-4.20", reasoning={"enabled": False}, temp=True, seed=True, conc=12),
    # Substituted for moonshotai/kimi-k2 mid-run. Kimi has exactly one provider
    # on OpenRouter (Novita), which rate-limited us to ~3% completion in 40
    # minutes with no alternate route to fall back to; finishing would have
    # taken about twelve hours. DeepSeek V3.2 keeps the slot's purpose - an
    # open-weight frontier model from a lab not otherwise represented - and has
    # 14 providers, so capacity is not a single point of failure. Reasoning is
    # off by default here (`default_enabled: false`) and disabled explicitly.
    dict(tier="frontier", id="deepseek/deepseek-v3.2",
         slug="deepseek-v3.2", reasoning={"enabled": False}, temp=True, seed=True, conc=12),
    dict(tier="frontier", id="openai/gpt-5.2",
         slug="gpt-5.2", reasoning={"effort": "none"}, temp=False, seed=True, conc=12),
    dict(tier="frontier", id="anthropic/claude-opus-5",
         slug="claude-opus-5", reasoning={"enabled": False}, temp=True, seed=False, conc=16),
]


def load_inputs() -> tuple[dict, dict, dict]:
    """`sample.json`, `prompts.json`, and `{rep: {node: rendering}}`."""
    sample = json.loads((HERE / "sample.json").read_text())
    prompts = json.loads((HERE / "prompts.json").read_text())
    catalogues: dict[str, dict[int, str]] = {}
    for path in sorted((REPO / "translate").glob("*/etp_equations_*.json")):
        rows = json.loads(path.read_text())["equations"]
        key = next(k for k, v in rows[0].items()
                   if k not in ("node", "formal", "order", "variables") and isinstance(v, str))
        catalogues[path.parent.name] = {r["node"]: r[key] for r in rows}
        catalogues.setdefault("etp_canonical", {r["node"]: r["formal"] for r in rows})
    return sample, prompts, catalogues


def tasks_for(model: dict, sample: dict, reps: list[str], smoke: int | None,
              phase: str = "all") -> list[tuple]:
    """Every `(rep, node, k)` this model must answer, in shuffled order.

    `phase` splits the sweep: "main" is k=0 over all 500 equations — the
    headline result — and "repeat" is k=1,2 over the 150-equation subset. Main
    runs first so that a run cut short still yields the primary measurement.
    """
    # A smoke run takes an evenly spaced slice, not the first N: the sample is
    # sorted by node, so the head is all order-1 laws and would never exercise
    # the long-answer path that matters.
    rows = (sample["equations"][::max(1, len(sample["equations"]) // smoke)][:smoke]
            if smoke else sample["equations"])
    repeats = set(sample["repeat_nodes"]) if not smoke else set()
    ks = {"main": (0,), "repeat": (1, 2), "all": (0, 1, 2)}[phase]
    out = [(rep, r["node"], k)
           for rep in reps for r in rows
           for k in range(3 if r["node"] in repeats else 1) if k in ks]
    random.Random(TASK_SEED + MODELS.index(model)).shuffle(out)
    return out


def header_for(model: dict, prompts: dict, sample: dict) -> dict:
    """The identity a checkpoint file must agree with to be resumable."""
    return {
        "_header": True,
        "model": model["id"],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE if model["temp"] else None,
        "reasoning": model["reasoning"],
        "sample_seed": sample["meta"]["seed"],
        "sample_count": sample["meta"]["count"],
        "frame_sha256": prompts["meta"]["frame_sha256"],
    }


class Checkpoints:
    """The 18 per-representation JSONL files for one model.

    One file per representation keeps the results beside the prompts that
    produced them, which is how the directory is laid out; the write lock keeps
    the shuffled, threaded call order from interleaving two rows on one line.
    """

    def __init__(self, model: dict, reps: list[str], header: dict, tag: str):
        self.model, self.header, self.tag = model, header, tag
        self.lock = threading.Lock()
        self.handles: dict[str, object] = {}
        self.done: set[tuple] = set()
        self.paths = {rep: HERE / rep / f"{tag}{model['slug']}.jsonl" for rep in reps}
        for rep, path in self.paths.items():
            if path.exists():
                self._resume(rep, path)

    def _resume(self, rep: str, path: Path) -> None:
        """Read completed keys, refusing a file written under another config."""
        with path.open(encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue                      # torn final line: it will be redone
                if row.get("_header"):
                    mismatch = {k: (row.get(k), v) for k, v in self.header.items()
                                if row.get(k) != v}
                    if mismatch:
                        raise SystemExit(
                            f"{path} was written under a different configuration; "
                            f"refusing to mix.\n  differences (file, now): {mismatch}\n"
                            "  move the file aside to start over."
                        )
                    continue
                if "rep" in row and "error" not in row:
                    # Error rows are deliberately not marked done: a transient
                    # failure must be retried on the next run, not frozen into a
                    # permanent hole. grade.py keeps the last row per key.
                    self.done.add((row["rep"], row["node"], row["k"]))

    def write(self, row: dict) -> None:
        """Append one row and flush it."""
        rep = row["rep"]
        with self.lock:
            handle = self.handles.get(rep)
            if handle is None:
                path = self.paths[rep]
                fresh = not path.exists() or path.stat().st_size == 0
                handle = self.handles[rep] = path.open("a", encoding="utf-8")
                if fresh:
                    handle.write(json.dumps(self.header) + "\n")
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()

    def close(self) -> None:
        with self.lock:
            for handle in self.handles.values():
                handle.close()
            self.handles.clear()


def _filtered(body: dict, choice: dict) -> bool:
    """Whether a 200 response is really a refusal with nothing in it."""
    content = (choice.get("message") or {}).get("content")
    return choice.get("finish_reason") == "content_filter" or not (content or "").strip()


def send(client, model: dict, prompt: str, k: int) -> dict:
    """One call, with the transient and content-filter ladders."""
    payload = {
        "model": model["id"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "usage": {"include": True},
    }
    if model["temp"]:
        payload["temperature"] = TEMPERATURE
    if model["seed"]:
        payload["seed"] = SEED + k
    if model["reasoning"] is not None:
        payload["reasoning"] = model["reasoning"]

    started = time.monotonic()
    attempts, retries = 0, 0
    retried_plain = switched_provider = False
    while True:
        attempts += 1
        try:
            body, sdk_retries = openrouter.chat(client, payload)
            retries += sdk_retries
        except openrouter.OpenRouterError as exc:
            if ("providers have been ignored" in str(exc)) and payload.pop("provider", None):
                retries += 1
                continue
            if exc.status in TRANSIENT and attempts <= BACKOFF_ATTEMPTS:
                time.sleep(BACKOFF_BASE_S * (2 ** (attempts - 1))
                           * (0.5 + (threading.get_ident() % 1000) / 1000))
                retries += 1
                continue
            return {"error": str(exc)[:300], "latency_s": round(time.monotonic() - started, 2),
                    "retries": retries}

        choice = (body.get("choices") or [{}])[0]
        finish = choice.get("finish_reason")
        empty = not ((choice.get("message") or {}).get("content") or "").strip()

        # Two different failures that look alike. A real `content_filter` is
        # worth routing around; a merely empty body is usually transient and
        # must not be, because ignoring providers one after another exhausts
        # them and turns a retryable blip into a hard 404 (which is exactly
        # what the smoke run did to kimi-k2 three times).
        if (finish == "content_filter" or empty) and attempts <= BACKOFF_ATTEMPTS:
            if not retried_plain:
                retried_plain = True
                retries += 1
                continue
            if finish == "content_filter" and not switched_provider:
                provider = body.get("provider")
                if provider:
                    switched_provider = True
                    payload["provider"] = {"ignore": [provider], "allow_fallbacks": True}
                    retries += 1
                    continue

        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        return {
            "content": (choice.get("message") or {}).get("content") or "",
            "finish": choice.get("finish_reason"),
            "provider": body.get("provider"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
            "cost": usage.get("cost"),
            "latency_s": round(time.monotonic() - started, 2),
            "retries": retries,
            "filtered": _filtered(body, choice),
        }


def run_model(model: dict, sample: dict, prompts: dict, catalogues: dict,
              reps: list[str], smoke: int | None, tag: str, phase: str = "all") -> dict:
    """Answer every outstanding task for one model."""
    header = header_for(model, prompts, sample)
    book = Checkpoints(model, reps, header, tag)
    todo = [t for t in tasks_for(model, sample, reps, smoke, phase)
            if t not in book.done]
    client = openrouter.make_client(openrouter.load_api_key())
    counters = {"done": 0, "error": 0, "filtered": 0, "cost": 0.0}
    lock = threading.Lock()
    started = time.time()

    def one(task):
        rep, node, k = task
        prompt = prompts["representations"][rep]["template"].replace(
            "{body}", catalogues[rep][node])
        result = send(client, model, prompt, k)
        row = {"rep": rep, "node": node, "k": k, "model": model["id"],
               "tier": model["tier"], **result}
        book.write(row)
        with lock:
            counters["done"] += 1
            counters["error"] += "error" in result
            counters["filtered"] += bool(result.get("filtered"))
            counters["cost"] += result.get("cost") or 0
            if counters["done"] % 500 == 0 or counters["done"] == len(todo):
                rate = counters["done"] / max(time.time() - started, 1e-9)
                left = (len(todo) - counters["done"]) / max(rate, 1e-9)
                print(f"[{model['slug']:24}] {counters['done']:6,}/{len(todo):,} "
                      f"({rate:5.1f}/s, ~{left/60:5.1f} min left) "
                      f"err={counters['error']} filt={counters['filtered']} "
                      f"${counters['cost']:.2f}", flush=True)

    if todo:
        with ThreadPoolExecutor(max_workers=model["conc"]) as pool:
            list(pool.map(one, todo))
    book.close()
    return {"model": model["id"], "requested": len(todo),
            "already_done": len(book.done), **counters}


def status(reps: list[str], sample: dict, tag: str) -> None:
    """Read-only progress, per model and per representation."""
    repeats = set(sample["repeat_nodes"])
    expect_per_rep = sum(3 if r["node"] in repeats else 1 for r in sample["equations"])
    total = expect_per_rep * len(reps)
    print(f"{'model':26} {'rows':>8} {'of':>8} {'%':>6} {'err':>5} {'filt':>5} {'cost':>8}")
    for model in MODELS:
        rows = err = filt = 0
        cost = 0.0
        for rep in reps:
            path = HERE / rep / f"{tag}{model['slug']}.jsonl"
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("_header"):
                    continue
                rows += 1
                err += "error" in row
                filt += bool(row.get("filtered"))
                cost += row.get("cost") or 0
        print(f"{model['slug']:26} {rows:8,} {total:8,} {rows/total*100:5.1f}% "
              f"{err:5} {filt:5} ${cost:7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--smoke", type=int, default=None,
                        help="only the first N sampled equations, k=0 only, into smoke- files")
    parser.add_argument("--status", action="store_true", help="read-only progress")
    parser.add_argument("--models", nargs="*", default=None, help="slugs to run")
    parser.add_argument("--phase", choices=("main", "repeat", "all"), default="all",
                        help="main = k0 over all 500; repeat = k1,k2 over the 150 subset")
    args = parser.parse_args()

    sample, prompts, catalogues = load_inputs()
    reps = sorted(prompts["representations"])
    tag = "smoke-" if args.smoke else "raw-"

    if args.status:
        status(reps, sample, tag)
        return

    models = [m for m in MODELS if not args.models or m["slug"] in args.models]
    print(f"{len(models)} models x {len(reps)} representations, "
          f"{'smoke: ' + str(args.smoke) + ' equations' if args.smoke else 'full sample'}"
          f", phase={args.phase}",
          flush=True)
    started = time.time()
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        summaries = list(pool.map(
            lambda m: run_model(m, sample, prompts, catalogues, reps, args.smoke, tag,
                                args.phase), models))
    elapsed = time.time() - started
    print(f"\n{'model':42} {'new':>7} {'skipped':>8} {'err':>5} {'filt':>5} {'cost':>8}")
    for s in summaries:
        print(f"{s['model']:42} {s['requested']:7,} {s['already_done']:8,} "
              f"{s['error']:5} {s['filtered']:5} ${s['cost']:7.3f}")
    print(f"total ${sum(s['cost'] for s in summaries):.2f} in {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
