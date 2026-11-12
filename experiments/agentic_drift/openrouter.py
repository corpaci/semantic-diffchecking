"""OpenRouter non-streaming transport with explicit provenance and no automatic retries."""
import asyncio
import hashlib
import json
from decimal import Decimal

from .budget import BudgetError, money

BASE_URL = "https://openrouter.ai/api/v1"


class RouterError(RuntimeError):
    def __init__(self, category, detail=""):
        self.category = category
        self.detail = detail
        super().__init__(category + (": " + detail if detail else ""))


def definite_unfunded_rejection(status, body):
    """Recognize a gateway rejection before generation, not an ambiguous provider failure."""
    if status != 402 or not isinstance(body, dict):
        return False
    error = body.get("error")
    if not isinstance(error, dict) or error.get("code") != 402:
        return False
    metadata = error.get("metadata")
    return (isinstance(metadata, dict) and metadata.get("limit_source") == "openrouter_credits"
            and "account never purchased credits" in str(error.get("message", "")).lower()
            and not body.get("id") and not body.get("choices") and not body.get("usage"))


def validate_config(config):
    if config.get("open_weights") is not True or not config.get("weights_source", "").startswith("https://"):
        raise ValueError("Provide an open-weight model and its public weights source")
    model = config.get("model", "")
    if not model or model.startswith("openrouter/") or ":" in model or len(model.split("/")) != 2:
        raise ValueError("Specify a concrete author/model ID, without automatic router variants")
    if not config.get("provider"):
        raise ValueError("Pin one provider endpoint")
    for name in ("max_tokens", "max_calls", "rounds", "timeout_seconds"):
        value = config.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    for name in ("total_budget_usd", "per_run_budget_usd"):
        if not 0 < money(config[name]) <= 50:
            raise ValueError("Budget must be positive and at most $50")
    if money(config["per_run_budget_usd"]) > money(config["total_budget_usd"]):
        raise ValueError("Per-run budget exceeds total budget")
    for rate in config["price_ceiling_per_million"].values():
        money(rate)
    if config.get("reasoning", {}).get("enabled") is not True or config["reasoning"].get("exclude") is not False:
        raise ValueError("Enable reasoning and retain returned reasoning fields")
    if not isinstance(config.get("temperature"), (int, float)) or not 0 <= config["temperature"] <= 2:
        raise ValueError("Invalid temperature")


def parse_response(body):
    if not isinstance(body, dict):
        raise RouterError("invalid_response", "Expected a JSON object")
    if body.get("error"):
        raise RouterError("provider_error", "Response contains a top-level error")
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise RouterError("invalid_choices", "Expected exactly one choice")
    choice = choices[0]
    if choice.get("error") or choice.get("finish_reason") == "error":
        raise RouterError("provider_error", "Choice contains an error")
    finish = choice.get("finish_reason")
    if finish == "length":
        raise RouterError("truncated_output", "Token budget exhausted; partial output is retained")
    if finish != "stop":
        raise RouterError("unexpected_finish_reason", str(finish))
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RouterError("invalid_message")
    if message.get("refusal") or message.get("tool_calls"):
        raise RouterError("refusal_or_unexpected_tool_call")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RouterError("empty_content", "Reasoning alone is not an implementation or artifact")
    return content


class OpenRouterSession:
    def __init__(self, config, key, trace, ledger, run_id, client=None):
        validate_config(config)
        self.config, self.trace, self.ledger, self.run_id = config, trace, ledger, run_id
        self.key = key
        self.client = client
        self.context_length = None
        self.lock = asyncio.Lock()
        self.failed = False
        self.cost = Decimal(0)
        self.requests = 0
        self.remaining = None
        self.usage_records = []

    async def __aenter__(self):
        if self.client is None:
            import httpx
            self.client = httpx.AsyncClient(timeout=httpx.Timeout(self.config["timeout_seconds"], connect=20),
                follow_redirects=False, trust_env=False, transport=httpx.AsyncHTTPTransport(retries=0))
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def _get(self, path, authenticated=False):
        import httpx
        headers = {"Authorization": "Bearer " + self.key} if authenticated else {}
        try:
            response = await self.client.get(BASE_URL + path, headers=headers)
        except httpx.HTTPError:
            raise RouterError("preflight_network_error") from None
        if response.status_code != 200:
            raise RouterError("preflight_http_error", str(response.status_code))
        try:
            result = response.json()
        except ValueError:
            raise RouterError("preflight_invalid_json") from None
        if not isinstance(result, dict):
            raise RouterError("preflight_invalid_json_shape")
        return result

    async def preflight(self):
        body = await self._get("/models/" + self.config["model"] + "/endpoints")
        data = body.get("data", {})
        if data.get("id") != self.config["model"]:
            raise RouterError("preflight_model_mismatch")
        candidates = [e for e in data.get("endpoints", []) if e.get("tag") == self.config["provider"]]
        if len(candidates) != 1:
            raise RouterError("preflight_provider_unavailable")
        endpoint = candidates[0]
        supported = set(endpoint.get("supported_parameters", []))
        if not {"reasoning", "max_tokens", "temperature"} <= supported:
            raise RouterError("preflight_unsupported_parameters")
        context_length = endpoint.get("context_length")
        if not isinstance(context_length, int) or context_length <= self.config["max_tokens"]:
            raise RouterError("preflight_context_too_small")
        maximum = endpoint.get("max_completion_tokens")
        if maximum is not None and self.config["max_tokens"] > maximum:
            raise RouterError("preflight_output_limit")
        for kind in ("prompt", "completion"):
            rate = money(endpoint.get("pricing", {}).get(kind)) * 1000000
            if rate > money(self.config["price_ceiling_per_million"][kind]):
                raise RouterError("preflight_price_ceiling", kind)
        request_price = money(endpoint.get("pricing", {}).get("request", 0))
        if request_price != 0:
            raise RouterError("preflight_unsupported_per_request_pricing")
        key_info = (await self._get("/key", authenticated=True)).get("data", {})
        limit = key_info.get("limit")
        if limit is None or not 0 < money(limit) <= money(self.config["total_budget_usd"]):
            raise RouterError("preflight_key_limit", "Use a dedicated key capped at $50 or less")
        if key_info.get("limit_reset") is not None:
            raise RouterError("preflight_recurring_key_limit", "Use a non-resetting experiment key")
        remaining = key_info.get("limit_remaining")
        if remaining is None or money(remaining) <= 0:
            raise RouterError("preflight_no_credit")
        # The key's spending allowance is not the account's purchased balance.
        # Exact balance lookup requires a management key; do not request one for inference.
        if key_info.get("is_free_tier") is True:
            raise RouterError("preflight_account_unfunded",
                "This account has not purchased credits. Add credits at https://openrouter.ai/settings/credits. "
                "The key's $50 spending limit does not fund the account.")
        self.context_length = context_length
        self.remaining = money(remaining)
        self.trace.event("openrouter_preflight", model=self.config["model"], endpoint=endpoint,
                         key_limit_usd=limit, key_remaining_usd=remaining,
                         account_balance_verified=False, account_is_free_tier=key_info.get("is_free_tier"),
                         config_sha256=hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest())

    async def complete(self, messages):
        import httpx
        async with self.lock:
            if self.failed:
                raise RouterError("request_blocked_after_failure")
            if self.context_length is None:
                raise RouterError("preflight_required")
            if self.requests >= self.config["max_calls"]:
                raise RouterError("model_call_limit")
            if not isinstance(messages, list) or not messages:
                raise RouterError("invalid_messages")
            # Conservative UTF-8 bound plus framing. Providers still enforce actual context limits.
            prompt_bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 256 * len(messages) + 256
            if prompt_bound + self.config["max_tokens"] > self.context_length:
                raise RouterError("context_precheck", "Request exceeds the conservative local context bound")
            rates = self.config["price_ceiling_per_million"]
            ceiling = (money(rates["prompt"]) * self.context_length
                       + money(rates["completion"]) * self.config["max_tokens"]) / 1000000
            if self.remaining is not None and ceiling > self.remaining:
                raise RouterError("insufficient_credit_before_request")
            reservation = self.ledger.reserve(self.run_id, ceiling, self.config["per_run_budget_usd"])
            self.requests += 1
            payload = {"model": self.config["model"], "messages": messages, "stream": False,
                       "temperature": self.config["temperature"], "max_tokens": self.config["max_tokens"],
                       "reasoning": self.config["reasoning"],
                       "provider": {"order": [self.config["provider"]], "allow_fallbacks": False,
                                    "require_parameters": True,
                                    "max_price": {k: float(v) for k, v in rates.items()}}}
            self.trace.event("openrouter_request", reservation_id=reservation, payload=payload,
                             prompt_token_bound=prompt_bound, reserved_usd=str(ceiling))
            generation_id = None
            try:
                response = await self.client.post(BASE_URL + "/chat/completions", json=payload,
                    headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
                try:
                    body = response.json()
                except ValueError:
                    self.trace.event("openrouter_invalid_body", reservation_id=reservation,
                                     http_status=response.status_code, body=response.text[:10000])
                    raise RouterError("invalid_json", str(response.status_code)) from None
                self.trace.event("openrouter_raw_response", reservation_id=reservation,
                    http_status=response.status_code, request_id=response.headers.get("x-request-id"),
                    retry_after=response.headers.get("retry-after"), body=body)
                cost_present = False
                if definite_unfunded_rejection(response.status_code, body):
                    self.ledger.settle(reservation, "0", None)
                    cost_present = True
                    self.trace.event("unbilled_gateway_rejection", reservation_id=reservation,
                        cost_usd="0", evidence="HTTP 402: account never purchased credits; no generation ID, choices, or usage")
                if isinstance(body, dict):
                    generation_id = body.get("id")
                    usage = body.get("usage")
                    if isinstance(usage, dict):
                        self.usage_records.append({"generation_id": generation_id, "usage": usage})
                    if isinstance(usage, dict) and usage.get("cost") is not None:
                        cost = money(usage["cost"])
                        self.ledger.settle(reservation, cost, generation_id)
                        self.cost += cost
                        cost_present = True
                        if self.remaining is not None:
                            self.remaining -= cost
                if response.status_code != 200:
                    category = {400: "bad_request_or_context", 401: "authentication", 402: "insufficient_credit",
                                403: "forbidden", 408: "provider_timeout", 429: "rate_limit",
                                502: "provider_unavailable", 503: "provider_unavailable"}.get(response.status_code, "http_error")
                    error_body = body.get("error") if isinstance(body, dict) else None
                    provider_message = error_body.get("message", "") if isinstance(error_body, dict) else ""
                    raise RouterError(category, f"HTTP {response.status_code}. {provider_message}".strip())
                content = parse_response(body)
                if not cost_present:
                    raise RouterError("missing_cost", "Preserve the response and reconcile before continuing")
                if body.get("model") != self.config["model"]:
                    raise RouterError("returned_model_mismatch")
                message = body["choices"][0]["message"]
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                details = message.get("reasoning_details")
                self.trace.event("reasoning_observation", generation_id=generation_id,
                    status="returned" if reasoning or details else "not_returned",
                    reasoning=reasoning, reasoning_details=details,
                    interpretation="provider_exposed_output_not_causal_ground_truth")
                if self.config["require_reasoning"] and not (reasoning or details):
                    raise RouterError("reasoning_not_returned")
                return content
            except BaseException as error:
                self.failed = True
                category = error.category if isinstance(error, RouterError) else (
                    "timeout_ambiguous_billing" if isinstance(error, httpx.TimeoutException) else type(error).__name__)
                self.ledger.unresolved(reservation, category, generation_id)
                self.trace.event("openrouter_error", category=category, reservation_id=reservation,
                                 generation_id=generation_id, automatic_retry=False)
                detail = getattr(error, "detail", "") or "Stopped; inspect the saved response and budget ledger"
                raise RouterError(category, self.trace.redact(detail)) from None
