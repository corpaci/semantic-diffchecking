"""Natural-language description -> formal ETP equation, graded by the oracle.

The closing half of the round trip. `translate/nl` turned each ETP law into a
description; this module hands a model the description *alone* — the formula is
never shown — asks for the identity back, and lets the formal oracle in
`../../oracle` say how the reconstruction relates to the law it came from:

    equivalent    the round trip preserved the law
    weaker        the model under-specified — the law it wrote is implied by,
                  but does not imply, the original
    stronger      the model over-specified
    incomparable  neither implies the other
    unknown       in the catalogue, but the implication graph does not settle it

The two functions this module exists for:

    check_description(client, model, intended, description, template, oracle=...)
        one description -> one graded record

    run_catalogue(model, descriptions_path, prompt, out_path)
        every description in a `translate/nl` output file, graded, summarized

Everything else is what 4694 paid calls needs and one call does not — a cost
estimate before the run, a checkpoint that survives an interruption, failures
recorded as rows rather than raised as exceptions, and eight requests in flight.
Those mechanisms are `describe.py`'s and are imported from it rather than
rewritten, so the two halves of the round trip cannot drift apart.

Two decisions worth knowing about:

* **The grade is a proof, not a string match.** Comparison goes through
  `SemanticOracle.compare`, so `a * b = b * a` and `x ◇ y = y ◇ x` are the same
  law, and a wrong answer is classified by *how* it is wrong rather than merely
  flagged as different.
* **Extraction is recorded.** A model asked for one line sometimes writes a
  paragraph. Candidate lines are tried until one maps to a node, and every row
  says whether the answer was used verbatim or scanned out of prose, so an
  accuracy figure can always be recomputed over the verbatim rows alone.
  `--strict` disables scanning entirely.

CLI:
    python3 reconstruct.py --model qwen/qwen3-30b-a3b \\
        --descriptions ../nl/descriptions-qwen3.json --out results-qwen3.json --dry-run
    python3 reconstruct.py --model qwen/qwen3-30b-a3b \\
        --descriptions ../nl/descriptions-qwen3.json --out results-qwen3.json --yes
    python3 reconstruct.py ... --resume            # continue an interrupted sweep
    python3 reconstruct.py --summarize results-qwen3.json      # no calls
    python3 reconstruct.py --model X --formal "x ◇ y = y ◇ x" --description "..."
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Both sibling packages are imported by path rather than installed: the oracle's
# modules import each other by top-level name, and `translate/nl` is a directory
# of scripts. Putting each on sys.path is both necessary and sufficient.
NL_DIR = Path(os.environ.get("TRANSLATE_NL_DIR", Path(__file__).resolve().parent.parent / "nl"))
ORACLE_DIR = Path(
    os.environ.get("TRANSLATE_ORACLE_DIR", Path(__file__).resolve().parents[2] / "oracle")
)
for _path in (NL_DIR, ORACLE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import openrouter  # noqa: E402  (path bootstrap must run first)
from openrouter import MissingCredentials, OpenRouterError  # noqa: E402

# The forward half's machinery, reused rather than reimplemented. `_usage` and
# `_load_checkpoint` are private to `describe` only in the sense that they are
# not part of its CLI; both solve exactly the problem this module also has, and
# a second copy of either would be a second thing to keep correct.
from describe import (  # noqa: E402
    REASONING_HEADROOM,
    build_payload,
    check_model,
    prompt_sha,
    utc_now,
    _load_checkpoint,
    _usage,
)
from mapper import NodeMapper  # noqa: E402
from oracle import SemanticOracle  # noqa: E402

PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_PROMPT = PROMPT_DIR / "reconstruct.txt"

# Where the description goes when the prompt names a slot for it.
DESCRIPTION_SLOT = "{description}"

# The oracle's labels, grouped the way the summary reports them. RESOLVED are
# the four the implication graph settles with proofs in both directions;
# everything in UNRESOLVED means the graph could not speak (or the answer never
# reached it), and is counted separately rather than folded into "wrong" — a
# reconstruction the oracle cannot judge is not evidence that the model failed.
CORRECT = ("equivalent",)
INCORRECT = ("weaker", "stronger", "incomparable")
RESOLVED = CORRECT + INCORRECT
UNRESOLVED = ("unknown", "outside-fragment", "parse-failure", "internal-error")

# An answer is one short line, so this budget is not sized for the answer: it is
# sized for the thinking in front of it. Reasoning models get REASONING_HEADROOM
# on top (as in `describe.py`) and still run out — at 200 here,
# `qwen/qwen3-30b-a3b` returned nothing on two of eight sampled laws, both cut
# off at exactly the limit, and both answered once the budget was raised. A cap
# costs nothing on a model that does not use it.
DEFAULT_MAX_TOKENS = 1000

# For the pre-flight estimate only, matching `describe.py`'s deliberately crude
# characters-per-token guard.
_CHARS_PER_TOKEN = 4
_ASSUMED_OUTPUT_TOKENS = 40

_FENCE = re.compile(r"```[a-zA-Z]*\n?(.*?)```", re.DOTALL)
_BULLET = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)")


def render_prompt(template: str, description: str) -> str:
    """Put `description` into `template`.

    `{description}` is substituted wherever it appears; a template without the
    placeholder gets the description appended at the end. Plain `str.replace`,
    not `str.format`, so braces elsewhere in a prompt are left alone.
    """
    if DESCRIPTION_SLOT in template:
        return template.replace(DESCRIPTION_SLOT, description)
    return f"{template.rstrip()}\n\n{description}"


# -- reading an equation out of an answer --------------------------------------


def _strip_label(line: str) -> str:
    """Drop a leading `Answer:` / `The identity is:` style label, if any.

    Only a colon that appears *before* the first `=` is treated as a label
    separator, so nothing inside the equation itself can be cut away.
    """
    head, sep, tail = line.partition("=")
    if not sep or ":" not in head:
        return line
    return f"{head.rsplit(':', 1)[1]}={tail}"


def extract_candidates(answer: str) -> list[str]:
    """Substrings of `answer` that might be the equation, best guess first.

    A model told to emit one line usually does, and then the whole answer is the
    equation — that candidate comes first, so the common case is exact. The rest
    of the list exists for the models that wrap it in prose: fenced code blocks,
    then the `=`-bearing lines from the bottom up (a chatty answer states its
    conclusion last), each also tried with a leading label removed.

    Only the shape is guessed at; nothing here alters operators or grouping, so
    a candidate is either the model's equation or fails to parse. The caller
    records which candidate was used.
    """
    found: list[str] = []

    def add(text: str) -> None:
        text = text.strip().strip("*").strip()
        if "=" in text and text not in found:
            found.append(text)

    body = answer.strip()
    add(body)
    for block in _FENCE.findall(body):
        add(block)
    for line in reversed(_FENCE.sub("\n", body).splitlines()):
        line = _BULLET.sub("", line).strip()
        add(line)
        add(_strip_label(line))
    return found


def grade(oracle: SemanticOracle, intended: "str | int", answer: str | None,
          *, strict: bool = False) -> dict:
    """Compare an answer against the intended law and return the graded fields.

    Tries each candidate from `extract_candidates` until one maps to an ETP
    node; if none does, the verdict from the first candidate is kept, so the row
    reports the actual parse failure rather than nothing. `strict=True` uses the
    answer verbatim and nothing else — the honest comparison when the question
    is how often a model follows the output instruction.

    Returns `{"label", "extracted", "extraction", "candidates_tried", "oracle"}`
    with `label` mirrored to the top level for filtering; `label` is None when
    there was no answer to grade.

    An answer that did not map carries `oracle.generated_tautology`: whether its
    two sides are the same term. Such a law holds in every magma, but the ETP
    catalogue lists only `x = x` for that, so `x ◇ x = x ◇ x` is reported by the
    mapper as `internal-error` ("normalizer bug, please report"). The flag keeps
    a model answering with a tautology distinguishable from a real mapper bug.
    """
    if not answer or not answer.strip():
        return {"label": None, "extracted": None, "extraction": None,
                "candidates_tried": 0, "oracle": None}

    candidates = [answer.strip()] if strict else extract_candidates(answer)
    if not candidates:  # nothing with an '=' in it anywhere
        candidates = [answer.strip()]

    chosen = verdict = None
    for index, candidate in enumerate(candidates):
        v = oracle.compare(intended, candidate)
        if verdict is None:
            chosen, verdict, tried = candidate, v, index + 1
        if v.generated["status"] == "mapped":
            chosen, verdict, tried = candidate, v, index + 1
            break

    tautology = None
    if verdict.generated["status"] != "mapped":
        parsed = oracle.mapper.map(chosen).equation
        tautology = bool(parsed and parsed.lhs == parsed.rhs)

    return {
        "label": verdict.label,
        "extracted": chosen,
        "extraction": "verbatim" if chosen == answer.strip() else "scanned",
        "candidates_tried": tried,
        "oracle": {
            "label": verdict.label,
            "generated_tautology": tautology,
            "forward": verdict.forward,
            "backward": verdict.backward,
            "evidence": verdict.evidence,
            "notes": verdict.notes,
            "intended_node": verdict.intended["node"],
            "intended_normalized": verdict.intended["normalized"],
            "generated_node": verdict.generated["node"],
            "generated_normalized": verdict.generated["normalized"],
            "generated_status": verdict.generated["status"],
            "generated_order": verdict.generated["order"],
            "generated_reason": verdict.generated["reason"],
        },
    }


# -- one call ------------------------------------------------------------------


def check_description(
    client,
    model: str,
    intended: "str | int",
    description: str,
    template: str,
    *,
    oracle: SemanticOracle,
    temperature: float | None = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    seed: int | None = None,
    supported: set[str] | None = None,
    price: tuple[float, float] | None = None,
    strict: bool = False,
) -> dict:
    """Ask `model` for the identity behind `description`, and grade the answer.

    `intended` is the law the description was written from — either its text or
    its ETP equation number; the model is never shown it. Returns a record and
    never raises: `status` is `ok` when the model produced text, `empty` when
    the call succeeded but returned none (usually a reasoning model that spent
    the whole budget thinking — `finish_reason` will say so), and `failed` when
    the call itself errored.
    """
    user_prompt = render_prompt(template, description)
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
            "answer": None,
            "status": "failed",
            "error": str(exc),
            "label": None,
            "latency_s": round(time.monotonic() - started, 3),
            "timestamp": utc_now(),
        }
    latency = round(time.monotonic() - started, 3)

    choices = response.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    # A refusal leaves `content` empty; keeping the refusal text means the row
    # records *why* there is no equation.
    text = (message.get("content") or message.get("refusal") or "").strip()

    record = {
        "answer": text or None,
        "status": "ok" if text else "empty",
        "finish_reason": choice.get("finish_reason"),
        "model_reported": response.get("model"),
        "upstream_provider": response.get("provider"),
        "usage": _usage(response.get("usage") or {}, price),
        "latency_s": latency,
        "attempts": attempts + sdk_retries,
        "timestamp": utc_now(),
    }
    record.update(grade(oracle, intended, text, strict=strict))
    if withheld or dropped:
        record["params_withheld"] = {**withheld, **dropped}
    return record


def check(
    model: str,
    formal: "str | int",
    description: str,
    *,
    prompt: str | None = None,
    equations_path: str | Path | None = None,
    api_key: str | None = None,
    **kwargs,
) -> dict:
    """One description, one call, one grade — building its own client and oracle.

    The convenience wrapper for a single pair or an interactive session; a sweep
    should use `run_catalogue`, which builds both once and reuses them.
    """
    template = prompt if prompt is not None else DEFAULT_PROMPT.read_text(encoding="utf-8")
    client = openrouter.make_client(openrouter.load_api_key(api_key))
    catalogue = openrouter.catalogue()
    check_model(model, catalogue)
    return check_description(
        client, model, formal, description, template,
        oracle=load_oracle(equations_path),
        supported=catalogue.supported(model), price=catalogue.price(model),
        **kwargs,
    )


def load_oracle(equations_path: str | Path | None = None) -> SemanticOracle:
    """Build the oracle, optionally against a specific `equations.txt`.

    `SemanticOracle` resolves the catalogue itself; the swap here keeps the
    `--equations` flag meaning the same thing it means in `describe.py`, so a
    sweep and its grading read the same file.
    """
    oracle = SemanticOracle()
    if equations_path:
        oracle.mapper = NodeMapper(str(equations_path))
    return oracle


# -- the sweep -----------------------------------------------------------------


def load_descriptions(path: str | Path) -> tuple[dict, list[dict]]:
    """Read a `translate/nl` output file as `(meta, rows)`.

    Accepts either the `{meta, descriptions}` file or a bare list of rows, so a
    hand-assembled subset can be graded without faking a meta block.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {}, data
    rows = data.get("descriptions")
    if rows is None:
        raise SystemExit(f"{path}: not a descriptions file (no 'descriptions' key)")
    return data.get("meta") or {}, rows


def estimate_cost(model: str, template: str, rows: list[dict], *, catalogue=None) -> dict:
    """Rough pre-flight cost for one call per row in `rows`.

    Unlike the forward half, the variable part of the prompt is known before the
    run — these are the actual descriptions — so the input side is averaged over
    them rather than assumed. Still characters over four: an order-of-magnitude
    guard, not accounting.
    """
    catalogue = catalogue or openrouter.catalogue()
    price = catalogue.price(model)
    lengths = [len(r["description"]) for r in rows if r.get("description")]
    average = sum(lengths) / len(lengths) if lengths else 0
    input_tokens = (len(render_prompt(template, "")) + average) / _CHARS_PER_TOKEN
    estimate = {
        "priced": price is not None,
        "calls": len(lengths),
        "assumed_input_tokens_per_call": round(input_tokens),
        "assumed_output_tokens_per_call": _ASSUMED_OUTPUT_TOKENS,
        "total_usd": None,
    }
    if price:
        per_call = input_tokens * price[0] + _ASSUMED_OUTPUT_TOKENS * price[1]
        estimate["usd_per_call"] = round(per_call, 8)
        estimate["total_usd"] = round(per_call * len(lengths), 4)
    return estimate


def _run_identity(model: str, template: str, params: dict, strict: bool,
                  source: dict, source_path: Path) -> dict:
    """What a checkpoint must match for a resume to be legitimate.

    The reconstructing model, its prompt, the generation parameters, the
    extraction rule — and the *source* descriptions, identified by the model and
    prompt that produced them. Resuming across a change to any of these would
    blend two experiments into one output file.
    """
    return {
        "model": model,
        "prompt_sha": prompt_sha(template),
        "params": params,
        "strict": strict,
        "descriptions": {
            "path": str(source_path),
            "model": source.get("model"),
            "prompt_sha": source.get("prompt_sha"),
        },
    }


def run_catalogue(
    model: str,
    descriptions_path: str | Path,
    prompt: str,
    out_path: str | Path,
    *,
    nodes: list[int] | None = None,
    limit: int | None = None,
    temperature: float | None = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    seed: int | None = None,
    strict: bool = False,
    equations_path: str | Path | None = None,
    concurrency: int = 8,
    timeout: float = 120.0,
    api_key: str | None = None,
    resume: bool = False,
    max_spend_usd: float | None = None,
    progress: bool = True,
) -> dict:
    """Reconstruct an equation from every description in the file, and grade it.

    `prompt` is the template text (not a path). Writes
    `{"meta", "summary", "results"}` to `out_path`, one row per description in
    node order — including the rows that had no description to send and the
    calls that failed, because excluding them would quietly turn "the model
    failed on 80 laws" into a higher score on the rest. Returns the `meta` block.

    `resume=True` continues an interrupted sweep from `<out_path>.partial.jsonl`;
    `max_spend_usd` stops launching calls once reported spend passes it;
    `strict=True` grades the answer verbatim instead of scanning prose for it.
    """
    out_path, descriptions_path = Path(out_path), Path(descriptions_path)
    checkpoint_path = out_path.with_suffix(out_path.suffix + ".partial.jsonl")

    try:
        api_key = openrouter.load_api_key(api_key)
    except MissingCredentials as exc:
        raise SystemExit(str(exc)) from None

    catalogue = openrouter.catalogue()
    check_model(model, catalogue)
    supported, price = catalogue.supported(model), catalogue.price(model)

    source_meta, source_rows = load_descriptions(descriptions_path)
    sources = {row["node"]: row for row in source_rows}
    selected = sorted(set(nodes) & set(sources) if nodes else sources)
    if nodes and (missing := sorted(set(nodes) - set(sources))):
        raise SystemExit(f"{descriptions_path} has no rows for nodes {missing}")
    if limit:
        selected = selected[:limit]

    params = {"temperature": temperature, "max_tokens": max_tokens, "seed": seed}
    identity = _run_identity(model, prompt, params, strict, source_meta, descriptions_path)
    done = _load_checkpoint(checkpoint_path, identity) if resume else {}
    if not resume and checkpoint_path.exists():
        checkpoint_path.unlink()
    pending = [n for n in selected if n not in done]

    oracle = load_oracle(equations_path)
    client = openrouter.make_client(api_key, timeout=timeout)
    lock = threading.Lock()
    state = {"spend": 0.0, "completed": len(done), "stopped": False,
             "correct": sum(r.get("label") in CORRECT for r in done.values()),
             "resolved": sum(r.get("label") in RESOLVED for r in done.values())}
    started_at, started = utc_now(), time.monotonic()

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_path.open("a" if done else "w", encoding="utf-8")
    if not done:
        checkpoint.write(json.dumps({"identity": identity, "started_at": started_at}) + "\n")
        checkpoint.flush()

    def work(node: int) -> dict:
        """One description: call the model, grade the answer, checkpoint."""
        source = sources[node]
        row = {
            "node": node,
            "formal": source.get("formal"),
            "source_status": source.get("status"),
            "description": source.get("description"),
            "description_echoes_notation": source.get("mentions_notation"),
        }
        # A row the forward half could not produce a description for has nothing
        # to reconstruct from. It is kept, marked, and never counted as an error
        # of *this* model.
        if not row["description"]:
            row.update(status="no-description", answer=None, label=None, timestamp=utc_now())
        elif state["stopped"]:
            row.update(status="skipped-budget", answer=None, label=None, timestamp=utc_now())
        else:
            row.update(check_description(
                client, model, node, row["description"], prompt,
                oracle=oracle, temperature=temperature, max_tokens=max_tokens,
                seed=seed, supported=supported, price=price, strict=strict,
            ))

        with lock:
            cost = (row.get("usage") or {}).get("cost_usd")
            if isinstance(cost, (int, float)):
                state["spend"] += cost
            state["completed"] += 1
            state["correct"] += row.get("label") in CORRECT
            state["resolved"] += row.get("label") in RESOLVED
            over_budget = max_spend_usd is not None and state["spend"] >= max_spend_usd
            if over_budget and not state["stopped"]:
                state["stopped"] = True
                print(f"\nmax spend ${max_spend_usd} reached after {state['completed']} calls; "
                      "remaining descriptions recorded as skipped-budget", file=sys.stderr)
            checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
            checkpoint.flush()  # a killed run must lose at most the in-flight calls
            if progress and state["completed"] % 25 == 0:
                elapsed = time.monotonic() - started
                rate = (state["completed"] - len(done)) / elapsed if elapsed else 0
                share = state["correct"] / state["resolved"] if state["resolved"] else 0
                print(f"  {state['completed']}/{len(selected)}  "
                      f"equivalent {state['correct']}/{state['resolved']} ({share:.1%})  "
                      f"${state['spend']:.4f}  {rate:.1f}/s", file=sys.stderr, flush=True)
        return row

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            rows = list(pool.map(work, pending))
    finally:
        checkpoint.close()

    all_rows = sorted([*done.values(), *rows], key=lambda r: r["node"])
    meta = _build_meta(
        model=model, prompt=prompt, params=params, strict=strict, rows=all_rows,
        source_meta=source_meta, source_path=descriptions_path, catalogue=catalogue,
        supported=supported, oracle=oracle, started_at=started_at,
        elapsed=round(time.monotonic() - started, 1), resumed=len(done),
        checkpoint=checkpoint_path,
    )
    summary = summarize(all_rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"meta": meta, "summary": summary, "results": all_rows},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return meta


def _build_meta(*, model, prompt, params, strict, rows, source_meta, source_path,
                catalogue, supported, oracle, started_at, elapsed, resumed, checkpoint) -> dict:
    """Assemble the run's provenance and totals."""
    providers: dict[str, int] = {}
    withheld: dict[str, str] = {}
    tokens_in = tokens_out = 0
    spend = 0.0
    estimated_spend = False

    for row in rows:
        if row.get("upstream_provider"):
            providers[row["upstream_provider"]] = providers.get(row["upstream_provider"], 0) + 1
        withheld.update(row.get("params_withheld") or {})
        usage = row.get("usage") or {}
        tokens_in += usage.get("input_tokens") or 0
        tokens_out += usage.get("output_tokens") or 0
        if isinstance(usage.get("cost_usd"), (int, float)):
            spend += usage["cost_usd"]
            estimated_spend |= usage.get("cost_source") == "estimated"

    return {
        "generator": "translate/nl_test/reconstruct.py",
        "model": model,
        "sdk": openrouter.sdk_version(),
        "prompt": prompt,
        "prompt_sha": prompt_sha(prompt),
        "params": params,
        "params_withheld": withheld or None,
        "supported_parameters": sorted(supported) if supported else None,
        "extraction": "strict" if strict else "scan-for-equation",
        "catalogue_source": catalogue.source,
        "descriptions": {
            "path": str(source_path),
            "model": source_meta.get("model"),
            "prompt_sha": source_meta.get("prompt_sha"),
            "equation_form": source_meta.get("equation_form"),
            "count": source_meta.get("count"),
        },
        "oracle": {
            "equations": oracle.mapper.equations_path,
            "matrix": {k: oracle.meta.get(k) for k in ("n", "source", "generated_at")
                       if k in oracle.meta},
        },
        "count": len(rows),
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


# -- the summary ---------------------------------------------------------------


def summarize(rows: list[dict]) -> dict:
    """Count the graded rows into the headline result.

    Three tiers, kept apart on purpose:

    * `resolved` — the oracle proved a relation. `correct` is the equivalent
      share of it; `incorrect` splits into weaker / stronger / incomparable,
      which is the finding worth having: *how* a round trip fails.
    * `unresolved` — the model answered but the answer never reached a verdict
      (unparseable, outside the order-4 fragment, or a pair the graph leaves
      open). Not evidence either way.
    * `not_attempted` — there was no answer to grade: no description existed
      (`no-description`), the call errored (`failed`), the budget stopped it
      (`skipped-budget`), or the model returned no text (`empty`). The last of
      those *is* the model's doing when it is a refusal, so it is reported by
      status rather than folded into either of the tiers above.

    Both accuracy figures are reported because neither is the obviously right
    one: over `resolved` it answers "when the oracle can judge, how often is the
    round trip faithful", over `answered` it charges every unparseable answer as
    a miss. `exact_node` counts answers landing on the *same* catalogue node,
    which is `equivalent` minus the pairs proved equivalent across two nodes.
    """
    labels = Counter(row["label"] for row in rows if row.get("label"))
    statuses = Counter(row.get("status") for row in rows)
    extraction = Counter(row["extraction"] for row in rows if row.get("extraction"))

    answered = statuses.get("ok", 0)
    resolved = sum(labels[label] for label in RESOLVED)
    correct = sum(labels[label] for label in CORRECT)
    incorrect = {label: labels[label] for label in INCORRECT}
    unresolved = {label: labels[label] for label in UNRESOLVED}
    exact_node = sum(
        1 for row in rows
        if (row.get("oracle") or {}).get("generated_node") is not None
        and row["oracle"]["generated_node"] == row["oracle"]["intended_node"]
    )
    tautologies = sum(1 for row in rows if (row.get("oracle") or {}).get("generated_tautology"))

    def share(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "rows": len(rows),
        "statuses": dict(statuses.most_common()),
        "answered": answered,
        "labels": dict(labels.most_common()),
        "resolved": resolved,
        "correct": {"equivalent": correct},
        "incorrect": {"total": sum(incorrect.values()), **incorrect},
        "unresolved": {"total": sum(unresolved.values()), **unresolved},
        "not_attempted": {
            "total": len(rows) - answered,
            **{s: n for s, n in statuses.items() if s != "ok"},
        },
        "accuracy_over_resolved": share(correct, resolved),
        "accuracy_over_answered": share(correct, answered),
        "exact_node": exact_node,
        "tautology_answers": tautologies,
        "extraction": dict(extraction),
    }


def print_summary(summary: dict, *, out=sys.stderr) -> None:
    """Print a summary as the run's closing lines."""
    print(f"\nrows: {summary['rows']}  answered: {summary['answered']}  "
          f"statuses: {summary['statuses']}", file=out)
    print(f"resolved by the oracle: {summary['resolved']}", file=out)
    print(f"  correct   equivalent   {summary['correct']['equivalent']}", file=out)
    for label in INCORRECT:
        print(f"  incorrect {label:<12} {summary['incorrect'][label]}", file=out)
    unresolved = {k: v for k, v in summary["unresolved"].items() if k != "total" and v}
    print(f"unresolved: {summary['unresolved']['total']} {unresolved or ''}"
          + (f"  (of which {summary['tautology_answers']} answered with a tautology)"
             if summary.get("tautology_answers") else ""), file=out)
    print(f"not attempted: {summary['not_attempted']['total']}", file=out)
    accuracy = summary["accuracy_over_resolved"]
    answered = summary["accuracy_over_answered"]
    print(f"equivalent share: {accuracy:.1%} of resolved, {answered:.1%} of answered"
          if accuracy is not None else "equivalent share: n/a (nothing resolved)", file=out)
    print(f"same catalogue node: {summary['exact_node']}   "
          f"extraction: {summary['extraction']}", file=out)


# -- CLI -----------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Reconstruct ETP equations from their natural-language "
                    "descriptions and grade them with the formal oracle."
    )
    parser.add_argument("--model", help="OpenRouter model id, e.g. qwen/qwen3-30b-a3b")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT,
                        help=f"prompt template file (default {DEFAULT_PROMPT.name})")
    parser.add_argument("--descriptions", type=Path, default=None,
                        help="a translate/nl output JSON, e.g. ../nl/descriptions-qwen3.json")
    parser.add_argument("--out", type=Path, default=None, help="output JSON path")
    parser.add_argument("--summarize", type=Path, default=None, metavar="RESULTS.json",
                        help="recompute and print the summary of an existing "
                             "results file; makes no calls")

    single = parser.add_argument_group("single pair (instead of --descriptions)")
    single.add_argument("--formal", help="the intended equation (text or ETP number)")
    single.add_argument("--description", help="the description to reconstruct from")

    scope = parser.add_argument_group("scope")
    scope.add_argument("--nodes", default=None,
                       help="comma-separated ETP equation numbers (default: every row)")
    scope.add_argument("--limit", type=int, default=None, help="only the first N descriptions")
    scope.add_argument("--equations", type=Path, default=None,
                       help="path to equations.txt (default: the oracle's resolution)")
    scope.add_argument("--strict", action="store_true",
                       help="grade the answer verbatim instead of scanning prose for it")

    gen = parser.add_argument_group("generation")
    gen.add_argument("--temperature", type=float, default=0.0,
                     help="0.0 by default; withheld, and recorded as withheld, on models "
                          "whose OpenRouter entry does not accept it")
    gen.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                     help=f"output budget per answer (default {DEFAULT_MAX_TOKENS}; "
                          f"reasoning models get {REASONING_HEADROOM} more)")
    gen.add_argument("--seed", type=int, default=None)

    run = parser.add_argument_group("run")
    run.add_argument("--concurrency", type=int, default=8, help="requests in flight (default 8)")
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--resume", action="store_true", help="continue from <out>.partial.jsonl")
    run.add_argument("--max-spend", type=float, default=None, metavar="USD",
                     help="stop launching calls once reported spend reaches this")
    run.add_argument("--dry-run", action="store_true",
                     help="print the cost estimate and a rendered prompt; make no calls")
    run.add_argument("--yes", action="store_true",
                     help="skip the confirmation for a run costing over $1")

    args = parser.parse_args()

    if args.summarize:
        data = json.loads(args.summarize.read_text(encoding="utf-8"))
        print_summary(summarize(data["results"]), out=sys.stdout)
        return

    if not args.model:
        parser.error("--model is required")
    if not args.prompt.exists():
        raise SystemExit(f"prompt file not found: {args.prompt}")
    template = args.prompt.read_text(encoding="utf-8")

    # Single pair: one call, the verdict printed, nothing written.
    if args.description or args.formal:
        if not (args.description and args.formal):
            parser.error("--formal and --description must be given together")
        record = check(
            args.model, args.formal, args.description, prompt=template,
            equations_path=args.equations, temperature=args.temperature,
            max_tokens=args.max_tokens, seed=args.seed, strict=args.strict,
        )
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return

    if not (args.descriptions and args.out):
        parser.error("--descriptions and --out are required (or use --formal/--description)")

    source_meta, source_rows = load_descriptions(args.descriptions)
    nodes = [int(n) for n in args.nodes.split(",") if n.strip()] if args.nodes else None
    if nodes:
        source_rows = [r for r in source_rows if r["node"] in set(nodes)]
    if args.limit:
        source_rows = source_rows[: args.limit]

    check_model(args.model)
    estimate = estimate_cost(args.model, template, source_rows)
    print(f"model:  {args.model}", file=sys.stderr)
    print(f"prompt: {args.prompt} [{prompt_sha(template)}]", file=sys.stderr)
    print(f"source: {args.descriptions} "
          f"[described by {source_meta.get('model')}, prompt {source_meta.get('prompt_sha')}]",
          file=sys.stderr)
    print(f"calls:  {estimate['calls']} of {len(source_rows)} rows "
          f"({len(source_rows) - estimate['calls']} have no description)", file=sys.stderr)
    if estimate["total_usd"] is not None:
        print(f"estimated cost: ~${estimate['total_usd']} "
              f"(~${estimate.get('usd_per_call')}/call, assuming "
              f"{estimate['assumed_output_tokens_per_call']} output tokens)", file=sys.stderr)
    else:
        print("estimated cost: unknown (this model has no fixed per-token price)",
              file=sys.stderr)

    if args.dry_run:
        example = next((r for r in source_rows if r.get("description")), None)
        if example:
            print(f"\n--- rendered prompt for Equation {example['node']} "
                  f"({example['formal']}) ---\n"
                  f"{render_prompt(template, example['description'])}", file=sys.stderr)
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

    meta = run_catalogue(
        args.model, args.descriptions, template, args.out,
        nodes=nodes, limit=args.limit, temperature=args.temperature,
        max_tokens=args.max_tokens, seed=args.seed, strict=args.strict,
        equations_path=args.equations, concurrency=args.concurrency,
        timeout=args.timeout, resume=args.resume, max_spend_usd=args.max_spend,
    )

    if meta["params_withheld"]:
        for key, why in meta["params_withheld"].items():
            print(f"withheld: {key} — {why}", file=sys.stderr)
    if meta["upstream_providers"]:
        print(f"\nserved by: {meta['upstream_providers']}", file=sys.stderr)
    usage = meta["usage"]
    print(f"tokens: in={usage['input_tokens']:,} out={usage['output_tokens']:,}"
          f"  spend=${usage['cost_usd']:.4f}"
          + ("  (includes estimates)" if usage["cost_includes_estimates"] else ""),
          file=sys.stderr)
    print_summary(json.loads(args.out.read_text(encoding="utf-8"))["summary"])
    print(f"elapsed {meta['elapsed_s']}s", file=sys.stderr)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
