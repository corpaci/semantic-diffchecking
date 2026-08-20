"""Formal ETP equation -> natural-language description, via an OpenRouter model.

The one function this module exists for:

    describe_catalogue(model, prompt, out_path)

sends the same prompt 4694 times — once per ETP law, with the equation
substituted in — and writes `{meta, descriptions}` to `out_path`.

Everything else here exists because 4694 paid calls is not the same problem as
one paid call:

* **Nothing is lost to an interruption.** Each finished row is appended to
  `<out>.partial.jsonl` as it arrives, and `resume=True` picks up exactly where
  a killed run stopped. The checkpoint carries the model and a hash of the
  prompt, so a resume after *editing the prompt* refuses rather than silently
  mixing two experiments into one file.
* **The bill is knowable in advance.** OpenRouter publishes per-token prices, so
  the run is costed before it starts, and `max_spend_usd` stops it mid-flight if
  reality outruns the estimate.
* **A failed call is a row, not an exception.** Errors, refusals, and empty
  answers are recorded with a `status` and kept. Dropping them would quietly
  turn "the model refused on 40 laws" into "the model described 4654 laws".
* **Concurrency.** At one request at a time a sweep takes hours; the default
  eight workers bring it to minutes without tripping ordinary rate limits.

Prompts live in `prompts/*.txt` and are passed as text. A `{equation}`
placeholder is substituted; a prompt without one gets the equation appended at
the end. The exact prompt text and its hash go into the output, because a
description is only interpretable next to the instruction that produced it.

CLI:
    python3 describe.py --model qwen/qwen3-30b-a3b --prompt prompts/structural.txt \\
        --out descriptions-qwen3.json --dry-run
    python3 describe.py --model anthropic/claude-opus-5 --prompt prompts/structural.txt \\
        --out descriptions-opus.json --max-spend 20 --yes
    python3 describe.py ... --resume            # continue an interrupted sweep
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import openrouter
from openrouter import MissingCredentials, OpenRouterError

# The oracle package is imported by path rather than installed: its modules
# import each other by top-level name and locate their own data with absolute
# paths, so putting the directory on sys.path is both necessary and sufficient.
ORACLE_DIR = Path(
    os.environ.get("TRANSLATE_ORACLE_DIR", Path(__file__).resolve().parents[2] / "oracle")
)
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from mapper import NodeMapper  # noqa: E402  (path bootstrap must run first)

PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_PROMPT = PROMPT_DIR / "structural.txt"

# Where the equation goes when the prompt names a slot for it.
EQUATION_SLOT = "{equation}"

# Reasoning tokens count against the output budget, so a limit sized for the
# visible answer can be consumed entirely by reasoning — the call then returns
# empty content with `finish_reason="length"`. Models that can reason get this
# added on top of the requested budget.
REASONING_HEADROOM = 2048

# Characters per token, for the pre-flight cost estimate only. Deliberately
# crude: it is an order-of-magnitude guard, not accounting.
_CHARS_PER_TOKEN = 4
# Assumed length of a description, for the same estimate.
_ASSUMED_OUTPUT_TOKENS = 160

# Notation a description is not supposed to contain. Recorded per row as a flag,
# not treated as a verdict — see `mentions_notation`.
_NOTATION_MARKERS = ("◇", "\\diamond", "\\circ", "=")


def utc_now() -> str:
    """Current UTC time, ISO-8601 with a `Z` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prompt_sha(text: str) -> str:
    """Short content hash of a prompt, for provenance."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def render_prompt(template: str, equation: str) -> str:
    """Put `equation` into `template`.

    `{equation}` is substituted wherever it appears; a template without the
    placeholder gets the equation appended at the end, which is the shape
    described as "a prompt with the equation last". Plain `str.replace`, not
    `str.format`, so braces elsewhere in a prompt are left alone.
    """
    if EQUATION_SLOT in template:
        return template.replace(EQUATION_SLOT, equation)
    return f"{template.rstrip()}\n\n{equation}"


def mentions_notation(description: str) -> bool:
    """Whether a description echoes formal notation it was asked to avoid.

    A flag for filtering and inspection, not a judgment: a description that
    restates the formula defeats the purpose of the representation change, but
    deciding what counts as a failure is the analysis's job, not this module's.
    """
    return any(marker in description for marker in _NOTATION_MARKERS)


# -- one call -----------------------------------------------------------------


def build_payload(
    model: str,
    user_prompt: str,
    *,
    temperature: float | None,
    max_tokens: int,
    seed: int | None = None,
    supported: set[str] | None,
) -> tuple[dict, dict[str, str]]:
    """Build the request body, sending only parameters the model accepts.

    Returns `(payload, withheld)`. `withheld` records every requested parameter
    the catalogue says this model does not take, with the reason — through
    OpenRouter, `anthropic/claude-opus-5` accepts `temperature` while
    `openai/gpt-5-nano` does not, so the same `temperature=0` is a deterministic
    request on one model and silently impossible on the other. A run has to say
    which it got.
    """
    withheld: dict[str, str] = {}

    def accepts(name: str) -> bool:
        """Send `name` unless the catalogue explicitly says it is not taken."""
        return supported is None or name in supported

    reasons = supported is not None and (
        "reasoning" in supported or "reasoning_effort" in supported
    )
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": max_tokens + (REASONING_HEADROOM if reasons or supported is None else 0),
        "usage": {"include": True},
    }
    for name, value in (("temperature", temperature), ("seed", seed)):
        if value is None:
            continue
        if accepts(name):
            payload[name] = value
        else:
            withheld[name] = (
                f"{model} does not list {name!r} in its OpenRouter supported_parameters"
            )
    return payload, withheld


def describe_equation(
    client,
    model: str,
    equation: str,
    template: str,
    *,
    temperature: float | None = 0.0,
    max_tokens: int = 400,
    seed: int | None = None,
    supported: set[str] | None = None,
    price: tuple[float, float] | None = None,
) -> dict:
    """Ask the model to describe one equation; return a record, never raising.

    The record always carries `status`: `ok` when the model produced text,
    `empty` when the call succeeded but returned nothing (usually the whole
    budget went to reasoning tokens — the `finish_reason` says so), and `failed`
    when the call itself errored.
    """
    user_prompt = render_prompt(template, equation)
    payload, withheld = build_payload(
        model, user_prompt, temperature=temperature, max_tokens=max_tokens,
        seed=seed, supported=supported,
    )

    started = time.monotonic()
    try:
        (response, sdk_retries), dropped, attempts = openrouter.call_with_recovery(
            lambda p: openrouter.chat(client, p), payload
        )
    except OpenRouterError as exc:
        return {
            "description": None,
            "status": "failed",
            "error": str(exc),
            "latency_s": round(time.monotonic() - started, 3),
            "timestamp": utc_now(),
        }
    latency = round(time.monotonic() - started, 3)

    choices = response.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    # A refusal leaves `content` empty; keeping the refusal text means the row
    # records *why* there is no description.
    text = (message.get("content") or message.get("refusal") or "").strip()

    record = {
        "description": text or None,
        "status": "ok" if text else "empty",
        "finish_reason": choice.get("finish_reason"),
        "model_reported": response.get("model"),
        "upstream_provider": response.get("provider"),
        "usage": _usage(response.get("usage") or {}, price),
        "latency_s": latency,
        "attempts": attempts + sdk_retries,
        "timestamp": utc_now(),
    }
    if text:
        record["mentions_notation"] = mentions_notation(text)
    if withheld or dropped:
        record["params_withheld"] = {**withheld, **dropped}
    return record


def _usage(usage: dict, price: tuple[float, float] | None) -> dict:
    """Normalize token counts and attach a cost.

    OpenRouter reports `cost` on most routes; where it does not, the catalogue's
    per-token price gives an estimate marked `estimated`, so a total never
    silently mixes measured and inferred spend.
    """
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    cost, source = usage.get("cost"), "reported"
    if cost is None:
        if price and prompt is not None and completion is not None:
            cost = prompt * price[0] + completion * price[1]
            source = "estimated"
        else:
            source = None
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "cost_usd": round(cost, 8) if isinstance(cost, (int, float)) else None,
        "cost_source": source,
    }


# -- the sweep ----------------------------------------------------------------


def check_model(model: str, catalogue=None) -> None:
    """Fail early on a model id OpenRouter does not serve.

    A typo is worth catching before 4694 calls — or before a dry run reports a
    confident-looking estimate for a model that does not exist. Skipped when the
    catalogue could not be loaded at all, since being offline is not evidence
    that the id is wrong.
    """
    catalogue = catalogue or openrouter.catalogue()
    if not catalogue.load() or catalogue.entry(model) is not None:
        return
    stem = model.split("/")[-1][:8]
    near = [m for m in catalogue.ids() if stem in m][:5]
    raise SystemExit(
        f"OpenRouter does not list a model {model!r}"
        + (f"; did you mean one of {near}?" if near else "")
    )


def estimate_cost(model: str, template: str, count: int, *, catalogue=None) -> dict:
    """Rough pre-flight cost for `count` calls with this prompt.

    Crude by construction — prompt length in characters over four, plus an
    assumed description length — and reported as such. Its job is to catch the
    difference between a five-cent run and a fifty-dollar one before it starts,
    not to be accurate.
    """
    catalogue = catalogue or openrouter.catalogue()
    price = catalogue.price(model)
    input_tokens = len(render_prompt(template, "x ◇ y = y ◇ x")) / _CHARS_PER_TOKEN
    estimate = {
        "priced": price is not None,
        "calls": count,
        "assumed_input_tokens_per_call": round(input_tokens),
        "assumed_output_tokens_per_call": _ASSUMED_OUTPUT_TOKENS,
        "total_usd": None,
    }
    if price:
        per_call = input_tokens * price[0] + _ASSUMED_OUTPUT_TOKENS * price[1]
        estimate["usd_per_call"] = round(per_call, 8)
        estimate["total_usd"] = round(per_call * count, 4)
    return estimate


def _run_identity(model: str, template: str, form: str, params: dict) -> dict:
    """What a checkpoint must match for a resume to be legitimate.

    Model, prompt, and the parameters that shape the answer. Resuming across any
    change to these would blend two experiments into one output file, which is
    the failure the checkpoint exists to prevent.
    """
    return {
        "model": model,
        "prompt_sha": prompt_sha(template),
        "form": form,
        "params": params,
    }


def _load_checkpoint(path: Path, identity: dict) -> dict[int, dict]:
    """Read finished rows from a checkpoint, or refuse a mismatched one.

    Returns {node: row}. A truncated final line (the run was killed mid-write)
    is discarded rather than treated as corruption.
    """
    if not path.exists():
        return {}
    rows: dict[int, dict] = {}
    with path.open(encoding="utf-8") as f:
        header = f.readline().strip()
        try:
            stored = json.loads(header).get("identity")
        except json.JSONDecodeError:
            raise SystemExit(
                f"{path}: unreadable checkpoint header; delete it to start over"
            ) from None
        if stored != identity:
            raise SystemExit(
                f"{path} belongs to a different run and cannot be resumed:\n"
                f"  checkpoint: {json.dumps(stored, sort_keys=True)}\n"
                f"  requested:  {json.dumps(identity, sort_keys=True)}\n"
                "Use a different --out, or delete the checkpoint to start over."
            )
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # partial trailing write from a killed run
            rows[row["node"]] = row
    return rows


def describe_catalogue(
    model: str,
    prompt: str,
    out_path: str | Path,
    *,
    equations_path: str | Path | None = None,
    nodes: list[int] | None = None,
    limit: int | None = None,
    form: str = "etp",
    temperature: float | None = 0.0,
    max_tokens: int = 400,
    seed: int | None = None,
    concurrency: int = 8,
    timeout: float = 120.0,
    api_key: str | None = None,
    resume: bool = False,
    max_spend_usd: float | None = None,
    progress: bool = True,
) -> dict:
    """Describe every ETP equation with `model` and write the JSON to `out_path`.

    `prompt` is the template text (not a path): `{equation}` is substituted, or
    the equation is appended if the template has no placeholder.

    Returns the `meta` block that was written. The output file is
    `{"meta": ..., "descriptions": [...]}` with one row per equation, in node
    order, including the rows that failed.

    Notable keyword arguments: `nodes`/`limit` restrict which equations are sent
    (for a pilot); `form="latex"` substitutes the LaTeX rendering from
    `../latex` instead of the ETP text; `resume=True` continues an interrupted
    sweep from `<out_path>.partial.jsonl`; `max_spend_usd` stops launching new
    calls once the reported spend passes it.
    """
    out_path = Path(out_path)
    checkpoint_path = out_path.with_suffix(out_path.suffix + ".partial.jsonl")

    try:
        api_key = openrouter.load_api_key(api_key)
    except MissingCredentials as exc:
        raise SystemExit(str(exc)) from None

    catalogue = openrouter.catalogue()
    check_model(model, catalogue)
    supported, price = catalogue.supported(model), catalogue.price(model)

    mapper = NodeMapper(str(equations_path)) if equations_path else NodeMapper()
    selected = sorted(nodes) if nodes else list(range(1, len(mapper.laws) + 1))
    if limit:
        selected = selected[:limit]
    formal = {n: mapper.law_text(n) for n in selected}
    inputs = _prompt_inputs(formal, form)

    params = {"temperature": temperature, "max_tokens": max_tokens, "seed": seed}
    identity = _run_identity(model, prompt, form, params)
    done = _load_checkpoint(checkpoint_path, identity) if resume else {}
    if not resume and checkpoint_path.exists():
        checkpoint_path.unlink()
    pending = [n for n in selected if n not in done]

    client = openrouter.make_client(api_key, timeout=timeout)
    lock = threading.Lock()
    state = {"spend": 0.0, "completed": len(done), "stopped": False}
    started_at, started = utc_now(), time.monotonic()

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_path.open("a" if done else "w", encoding="utf-8")
    if not done:
        checkpoint.write(json.dumps({"identity": identity, "started_at": started_at}) + "\n")
        checkpoint.flush()

    def work(node: int) -> dict:
        """One equation: call the model, record, checkpoint."""
        if state["stopped"]:
            return {"node": node, "formal": formal[node], "status": "skipped-budget",
                    "description": None, "timestamp": utc_now()}
        record = describe_equation(
            client, model, inputs[node], prompt,
            temperature=temperature, max_tokens=max_tokens, seed=seed,
            supported=supported, price=price,
        )
        row = {"node": node, "formal": formal[node]}
        if form != "etp":
            row["prompt_input"] = inputs[node]
        row.update(record)

        with lock:
            cost = (row.get("usage") or {}).get("cost_usd")
            if isinstance(cost, (int, float)):
                state["spend"] += cost
            state["completed"] += 1
            over_budget = max_spend_usd is not None and state["spend"] >= max_spend_usd
            if over_budget and not state["stopped"]:
                state["stopped"] = True
                print(f"\nmax spend ${max_spend_usd} reached after {state['completed']} calls; "
                      "remaining equations recorded as skipped-budget", file=sys.stderr)
            checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
            checkpoint.flush()  # a killed run must lose at most the in-flight calls
            if progress and state["completed"] % 25 == 0:
                elapsed = time.monotonic() - started
                rate = (state["completed"] - len(done)) / elapsed if elapsed else 0
                print(f"  {state['completed']}/{len(selected)}  "
                      f"${state['spend']:.4f}  {rate:.1f}/s", file=sys.stderr, flush=True)
        return row

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            rows = list(pool.map(work, pending))
    finally:
        checkpoint.close()

    all_rows = sorted([*done.values(), *rows], key=lambda r: r["node"])
    meta = _build_meta(
        model=model, prompt=prompt, form=form, params=params, rows=all_rows,
        mapper=mapper, catalogue=catalogue, supported=supported,
        started_at=started_at, elapsed=round(time.monotonic() - started, 1),
        resumed=len(done), checkpoint=checkpoint_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"meta": meta, "descriptions": all_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return meta


def _prompt_inputs(formal: dict[int, str], form: str) -> dict[int, str]:
    """The text substituted into the prompt for each node.

    `etp` uses the catalogue line as-is. `latex` renders it with the sibling
    `../latex` module, which is a genuine experimental variable: the same law in
    two notations is the same law, so a difference in the descriptions is a
    finding about the model, not about the equation.
    """
    if form == "etp":
        return dict(formal)
    if form != "latex":
        raise ValueError(f"form must be 'etp' or 'latex', got {form!r}")
    latex_dir = Path(__file__).resolve().parents[1] / "latex"
    if str(latex_dir) not in sys.path:
        sys.path.insert(0, str(latex_dir))
    from latexify import to_latex

    return {node: to_latex(text) for node, text in formal.items()}


def _build_meta(*, model, prompt, form, params, rows, mapper, catalogue, supported,
                started_at, elapsed, resumed, checkpoint) -> dict:
    """Assemble the run's provenance and totals."""
    statuses: dict[str, int] = {}
    providers: dict[str, int] = {}
    withheld: dict[str, str] = {}
    tokens_in = tokens_out = 0
    spend = 0.0
    estimated_spend = False
    notation_echoes = 0

    for row in rows:
        statuses[row.get("status", "?")] = statuses.get(row.get("status", "?"), 0) + 1
        if row.get("upstream_provider"):
            providers[row["upstream_provider"]] = providers.get(row["upstream_provider"], 0) + 1
        withheld.update(row.get("params_withheld") or {})
        notation_echoes += bool(row.get("mentions_notation"))
        usage = row.get("usage") or {}
        tokens_in += usage.get("input_tokens") or 0
        tokens_out += usage.get("output_tokens") or 0
        if isinstance(usage.get("cost_usd"), (int, float)):
            spend += usage["cost_usd"]
            estimated_spend |= usage.get("cost_source") == "estimated"

    return {
        "generator": "translate/nl/describe.py",
        "model": model,
        "sdk": openrouter.sdk_version(),
        "prompt": prompt,
        "prompt_sha": prompt_sha(prompt),
        "equation_form": form,
        "params": params,
        "params_withheld": withheld or None,
        "supported_parameters": sorted(supported) if supported else None,
        "catalogue_source": catalogue.source,
        "source": mapper.equations_path,
        "count": len(rows),
        "statuses": dict(sorted(statuses.items(), key=lambda kv: -kv[1])),
        "descriptions_echoing_notation": notation_echoes,
        "upstream_providers": providers or None,
        "usage": {
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cost_usd": round(spend, 6),
            "cost_includes_estimates": estimated_spend,
        },
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_s": elapsed,
        "resumed_rows": resumed,
        "checkpoint": str(checkpoint),
    }


# -- CLI ----------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Describe every ETP equation in natural language with an OpenRouter model."
    )
    parser.add_argument("--model", required=True,
                        help="OpenRouter model id, e.g. qwen/qwen3-30b-a3b")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT,
                        help=f"prompt template file (default {DEFAULT_PROMPT.name})")
    parser.add_argument("--out", type=Path, required=True, help="output JSON path")

    scope = parser.add_argument_group("scope")
    scope.add_argument("--nodes", default=None,
                       help="comma-separated ETP equation numbers (default: all 4694)")
    scope.add_argument("--limit", type=int, default=None, help="only the first N equations")
    scope.add_argument("--equations", type=Path, default=None,
                       help="path to equations.txt (default: the oracle's resolution)")
    scope.add_argument("--form", choices=("etp", "latex"), default="etp",
                       help="notation substituted into the prompt (default etp)")

    gen = parser.add_argument_group("generation")
    gen.add_argument("--temperature", type=float, default=0.0,
                     help="0.0 by default; withheld, and recorded as withheld, on models "
                          "whose OpenRouter entry does not accept it")
    gen.add_argument("--max-tokens", type=int, default=400,
                     help="output budget per description (reasoning models get headroom)")
    gen.add_argument("--seed", type=int, default=None)

    run = parser.add_argument_group("run")
    run.add_argument("--concurrency", type=int, default=8, help="requests in flight (default 8)")
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--resume", action="store_true",
                     help="continue from <out>.partial.jsonl")
    run.add_argument("--max-spend", type=float, default=None, metavar="USD",
                     help="stop launching calls once reported spend reaches this")
    run.add_argument("--dry-run", action="store_true",
                     help="print the cost estimate and a rendered prompt; make no calls")
    run.add_argument("--yes", action="store_true",
                     help="skip the confirmation for a run costing over $1")

    args = parser.parse_args()

    if not args.prompt.exists():
        raise SystemExit(f"prompt file not found: {args.prompt}")
    template = args.prompt.read_text(encoding="utf-8")
    nodes = ([int(n) for n in args.nodes.split(",") if n.strip()] if args.nodes else None)

    check_model(args.model)
    mapper = NodeMapper(str(args.equations)) if args.equations else NodeMapper()
    count = len(nodes or range(len(mapper.laws)))
    if args.limit:
        count = min(count, args.limit)

    estimate = estimate_cost(args.model, template, count)
    print(f"model:  {args.model}", file=sys.stderr)
    print(f"prompt: {args.prompt} [{prompt_sha(template)}]", file=sys.stderr)
    print(f"calls:  {count}", file=sys.stderr)
    if estimate["total_usd"] is not None:
        print(f"estimated cost: ~${estimate['total_usd']} "
              f"(~${estimate.get('usd_per_call')}/call, assuming "
              f"{estimate['assumed_output_tokens_per_call']} output tokens)", file=sys.stderr)
    else:
        print("estimated cost: unknown (this model has no fixed per-token price)",
              file=sys.stderr)

    if args.dry_run:
        example = mapper.law_text(nodes[0] if nodes else 43)
        print("\n--- rendered prompt for Equation "
              f"{nodes[0] if nodes else 43} ---\n{render_prompt(template, example)}",
              file=sys.stderr)
        return

    total = estimate["total_usd"]
    if not args.yes and (total is None or total > 1.0):
        if not sys.stdin.isatty():
            raise SystemExit(
                "this run may cost more than $1 (or has no published price); "
                "re-run with --yes to confirm, or --dry-run to inspect it first"
            )
        if input("proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            raise SystemExit("aborted")

    meta = describe_catalogue(
        args.model, template, args.out,
        equations_path=args.equations, nodes=nodes, limit=args.limit, form=args.form,
        temperature=args.temperature, max_tokens=args.max_tokens, seed=args.seed,
        concurrency=args.concurrency, timeout=args.timeout,
        resume=args.resume, max_spend_usd=args.max_spend,
    )

    print(f"\nstatuses: {meta['statuses']}", file=sys.stderr)
    if meta["params_withheld"]:
        for key, why in meta["params_withheld"].items():
            print(f"withheld: {key} — {why}", file=sys.stderr)
    if meta["upstream_providers"]:
        print(f"served by: {meta['upstream_providers']}", file=sys.stderr)
    usage = meta["usage"]
    print(f"tokens: in={usage['input_tokens']:,} out={usage['output_tokens']:,}"
          f"  spend=${usage['cost_usd']:.4f}"
          + ("  (includes estimates)" if usage["cost_includes_estimates"] else ""),
          file=sys.stderr)
    print(f"descriptions echoing notation: {meta['descriptions_echoing_notation']}",
          file=sys.stderr)
    print(f"elapsed {meta['elapsed_s']}s", file=sys.stderr)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
