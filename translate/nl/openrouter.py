"""OpenRouter transport: credentials, the SDK client, the model catalogue.

One gateway, one key, one model-id string — closed models (Anthropic, OpenAI,
Google) and open ones (Qwen, Llama, DeepSeek, Mistral) reached identically, so
swapping the model under test is a flag rather than a rewrite.

Calls go through the official `openai` SDK pointed at OpenRouter's base URL,
which is the only dependency here. It brings connection pooling,
`retry-after`-aware retries on 429/5xx, and typed errors that already separate a
bad key from a bad parameter — all of which matter when a single run makes 4694
requests.

Three things do work beyond forwarding the request:

* **Parameter splitting.** OpenRouter accepts fields the OpenAI schema has never
  heard of (`provider`, `reasoning`, `usage`). The SDK rejects unknown keyword
  arguments, so `chat` partitions the request against the live signature of
  `chat.completions.create` and routes the remainder through `extra_body`.

* **The model catalogue** (`/models`, public, no key). Each entry lists the
  parameters that model actually accepts and its per-token price. That decides
  which parameters are safe to send — `openai/gpt-5-nano` does not take
  `temperature`, `anthropic/claude-opus-5` does — and makes a 4694-call run
  costable *before* it starts.

* **`call_with_recovery`.** A rejected parameter is dropped and the call
  retried, recorded rather than silently swallowed. Transient failures are
  deliberately not handled here: the SDK owns those, and its `retries_taken`
  comes back in the record.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import httpx
    import openai
except ImportError as exc:  # pragma: no cover - install-time path
    raise SystemExit(
        "the openai SDK is required:\n"
        "  uv pip install --python .venv/bin/python openai"
    ) from exc

BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODELS_PATH = "/models"

# Sent for attribution on OpenRouter's leaderboards; harmless.
APP_TITLE = "semantic-diffchecking"

# The SDK insists on a key even for endpoints that do not authenticate.
_NO_KEY_PLACEHOLDER = "unauthenticated"

# Request fields that may be dropped to recover from a rejection. `model`,
# `messages`, and the token limit are excluded: without them there is no call.
DROPPABLE = frozenset({
    "temperature", "top_p", "top_k", "min_p", "seed", "stop", "reasoning",
    "reasoning_effort", "include_reasoning", "usage", "provider",
    "frequency_penalty", "presence_penalty", "repetition_penalty",
})

CATALOGUE_PATH = Path(
    os.environ.get("TRANSLATE_CACHE", Path(__file__).parent / ".cache")
) / "openrouter-models.json"
CATALOGUE_TTL_S = 24 * 3600


class OpenRouterError(RuntimeError):
    """A request to OpenRouter failed.

    `status` is the HTTP status (None for a connection-level failure) and `body`
    the decoded error payload, so callers can classify without re-parsing text.
    """

    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class MissingCredentials(RuntimeError):
    """No OpenRouter API key could be found."""


def sdk_version() -> str:
    """Client library version, for the provenance record."""
    return f"openai {openai.__version__} via OpenRouter"


# -- credentials --------------------------------------------------------------


def _dotenv_values(path: Path) -> dict[str, str]:
    """Parse `KEY=value` lines from a `.env` file. Missing file -> empty dict.

    Deliberately minimal: no interpolation, no multi-line values. Enough to keep
    a key out of shell history and out of git without another dependency.
    """
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def load_api_key(explicit: str | None = None) -> str:
    """Find the OpenRouter API key, or explain where to put one.

    Order: an explicitly passed key, `OPENROUTER_API_KEY` in the environment,
    then a `.env` file in this directory, in `translate/`, or at the repo root.
    """
    if explicit:
        return explicit
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    here = Path(__file__).resolve().parent
    for candidate in (here / ".env", here.parent / ".env", here.parents[1] / ".env"):
        key = _dotenv_values(candidate).get("OPENROUTER_API_KEY")
        if key:
            return key
    raise MissingCredentials(
        "no OpenRouter API key found. Either:\n"
        "  export OPENROUTER_API_KEY=sk-or-...\n"
        f"or write it to {here / '.env'} as:\n"
        "  OPENROUTER_API_KEY=sk-or-...\n"
        "(that path is gitignored). Keys come from https://openrouter.ai/keys"
    )


# -- the client ---------------------------------------------------------------


def make_client(
    api_key: str | None = None,
    *,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> openai.OpenAI:
    """Build an `openai.OpenAI` client pointed at OpenRouter.

    `max_retries` is the SDK's transient-failure budget: it retries 408, 409,
    429, and 5xx with jittered backoff and honours `retry-after`. On a long
    sweep that is the difference between a rate limit costing a few seconds and
    costing the run.
    """
    return openai.OpenAI(
        base_url=BASE_URL,
        api_key=api_key or _NO_KEY_PLACEHOLDER,
        timeout=timeout,
        max_retries=max_retries,
        default_headers={"X-Title": APP_TITLE},
    )


def _as_error(exc: Exception) -> OpenRouterError:
    """Normalize an SDK exception into an `OpenRouterError`."""
    if isinstance(exc, openai.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else None
        message = (body or {}).get("error", {}).get("message") if body else None
        return OpenRouterError(
            f"HTTP {exc.status_code}: {message or exc.message}",
            status=exc.status_code,
            body=exc.body,
        )
    return OpenRouterError(f"{type(exc).__name__}: {exc}")


def _known_create_params() -> set[str]:
    """Parameter names `chat.completions.create` accepts as keyword arguments.

    Everything else has to travel via `extra_body`. Read from the live signature
    so the split tracks the installed SDK instead of a list that silently rots.
    """
    signature = inspect.signature(openai.resources.chat.completions.Completions.create)
    return set(signature.parameters) - {
        "self", "extra_headers", "extra_query", "extra_body", "timeout",
    }


_KNOWN_PARAMS = _known_create_params()


def chat(client: openai.OpenAI, payload: dict) -> tuple[dict, int]:
    """Send one chat completion; return the raw response body and retry count.

    The body is read from the raw HTTP response rather than the SDK's parsed
    model, because OpenRouter adds fields the OpenAI schema does not define —
    `provider`, `native_finish_reason`, `usage.cost` — and those are exactly the
    provenance worth recording.
    """
    known = {k: v for k, v in payload.items() if k in _KNOWN_PARAMS}
    extra = {k: v for k, v in payload.items() if k not in _KNOWN_PARAMS}

    try:
        raw = client.chat.completions.with_raw_response.create(
            **known, **({"extra_body": extra} if extra else {})
        )
    except openai.OpenAIError as exc:
        raise _as_error(exc) from None

    try:
        body = json.loads(raw.text)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"unreadable response body: {exc}") from None

    # OpenRouter can answer 200 with an error object instead of choices.
    if isinstance(body, dict) and body.get("error") and not body.get("choices"):
        error = body["error"]
        raise OpenRouterError(
            f"API error: {error.get('message', error)}",
            status=error.get("code") if isinstance(error.get("code"), int) else 200,
            body=body,
        )
    return body, getattr(raw, "retries_taken", 0)


def fetch_models(client: openai.OpenAI | None = None) -> dict:
    """Fetch the `/models` catalogue as OpenRouter returns it.

    Deliberately not `client.models.list()`: that parses into the OpenAI `Model`
    shape and drops the fields needed here — `supported_parameters`, `pricing`,
    `top_provider`.
    """
    client = client or make_client(timeout=30.0)
    try:
        response = client.get(MODELS_PATH, cast_to=httpx.Response)
    except openai.OpenAIError as exc:
        raise _as_error(exc) from None
    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"unreadable catalogue: {exc}") from None


# -- recovery -----------------------------------------------------------------


def is_bad_request(exc: OpenRouterError) -> bool:
    """Whether the request itself was rejected — the parameter-drop path."""
    return exc.status in (400, 422)


def unsupported_in(message: str, payload: dict) -> list[str]:
    """Droppable payload keys the error message complains about.

    Provider error text is not machine-readable but does name the offending
    field ("temperature: unsupported parameter"). Intersecting those names with
    the droppable keys actually present is a conservative reading: if nothing
    intersects, the caller raises rather than guessing.
    """
    low = message.lower()
    return sorted(k for k in payload if k in DROPPABLE and k.lower() in low)


def call_with_recovery(
    send: Callable[[dict], Any],
    payload: dict,
    *,
    max_attempts: int = 3,
) -> tuple[Any, dict[str, str], int]:
    """Call `send(payload)`, dropping parameters the model rejects.

    A bad request naming a droppable parameter has it removed and is retried,
    with the provider's own words recorded. Everything else propagates:
    transient failures were already retried inside the SDK, and a bad key,
    exhausted credits, or an unknown model cannot be fixed by trying again.

    Returns `(whatever send returned, {parameter: why dropped}, attempts)`.
    """
    dropped: dict[str, str] = {}
    payload = dict(payload)

    for attempt in range(1, max_attempts + 1):
        try:
            return send(payload), dropped, attempt
        except OpenRouterError as exc:
            bad = (
                unsupported_in(str(exc), payload)
                if is_bad_request(exc) and attempt < max_attempts
                else []
            )
            if not bad:
                raise
            for key in bad:
                payload.pop(key, None)
                dropped[key] = f"rejected by OpenRouter: {_snip(str(exc))}"

    raise OpenRouterError("exhausted attempts without a response")  # pragma: no cover


def _snip(message: str, limit: int = 200) -> str:
    """One-line, length-capped error text, safe to embed in a JSON record."""
    flat = " ".join(message.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# -- the model catalogue ------------------------------------------------------


class ModelCatalogue:
    """OpenRouter's model list: accepted parameters and per-token price.

    Fetched from the public `/models` endpoint and cached on disk for a day.
    Two uses: `supported(model)` decides which parameters are sent, and
    `price(model)` turns a token count into money — which is what lets a
    4694-call run be estimated before it starts and totalled after.

    Every lookup degrades rather than fails: an unreachable network falls back
    to a stale cache, and an unknown model returns None, which callers read as
    "send everything and let `call_with_recovery` sort it out".
    """

    def __init__(self, path: Path | None = None, *, ttl_s: float = CATALOGUE_TTL_S):
        self.path = Path(path) if path else CATALOGUE_PATH
        self.ttl_s = ttl_s
        self._by_id: dict[str, dict] | None = None
        self.source: str | None = None      # network | cache | stale-cache | None

    def _fresh_enough(self) -> bool:
        """Whether the on-disk copy is younger than the TTL."""
        try:
            return (time.time() - self.path.stat().st_mtime) < self.ttl_s
        except OSError:
            return False

    def load(self, *, refresh: bool = False) -> dict[str, dict]:
        """Return {model_id: entry}, fetching or reusing the cache as needed."""
        if self._by_id is not None and not refresh:
            return self._by_id

        if not refresh and self._fresh_enough():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._by_id = {m["id"]: m for m in data.get("data", [])}
                self.source = "cache"
                return self._by_id
            except (OSError, json.JSONDecodeError, KeyError):
                pass  # a corrupt cache is a refetch, not an error

        try:
            data = fetch_models()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)
            self.source = "network"
        except OpenRouterError:
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    self.source = "stale-cache"
                except (OSError, json.JSONDecodeError):
                    self._by_id = {}
                    return self._by_id
            else:
                self._by_id = {}
                return self._by_id

        self._by_id = {m["id"]: m for m in data.get("data", []) if "id" in m}
        return self._by_id

    def entry(self, model: str) -> dict | None:
        """The catalogue entry for `model`, or None if it is not listed."""
        return self.load().get(model)

    def supported(self, model: str) -> set[str] | None:
        """Parameter names `model` accepts, or None when that is unknown.

        None means "no information" (model unlisted, or catalogue unreachable)
        and must not be read as "supports nothing".
        """
        entry = self.entry(model)
        if not entry or "supported_parameters" not in entry:
            return None
        return set(entry["supported_parameters"])

    def price(self, model: str) -> tuple[float, float] | None:
        """(prompt, completion) USD per token, or None if not priced.

        Variable-price routes such as `openrouter/auto` report -1; those return
        None rather than a nonsense estimate.
        """
        entry = self.entry(model)
        if not entry:
            return None
        pricing = entry.get("pricing") or {}
        try:
            prompt = float(pricing.get("prompt", -1))
            completion = float(pricing.get("completion", -1))
        except (TypeError, ValueError):
            return None
        return None if prompt < 0 or completion < 0 else (prompt, completion)

    def ids(self) -> list[str]:
        """Every model id OpenRouter currently serves, sorted."""
        return sorted(self.load())


_CATALOGUE: ModelCatalogue | None = None


def catalogue() -> ModelCatalogue:
    """The process-wide `ModelCatalogue`."""
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = ModelCatalogue()
    return _CATALOGUE
