"""Offline protocol and spending tests. HTTPX MockTransport never contacts OpenRouter."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from .budget import Ledger, BudgetError, money
from .openrouter import OpenRouterSession, RouterError, parse_response, validate_config, definite_unfunded_rejection
from .trace import Trace

CONFIG = json.loads(Path(__file__).with_name("openrouter_config.json").read_text())


def endpoint():
    return {"data": {"id": CONFIG["model"], "endpoints": [{"tag": CONFIG["provider"],
        "context_length": 128000, "max_completion_tokens": 16384,
        "pricing": {"prompt": "0.00000045", "completion": "0.0000035"},
        "supported_parameters": ["reasoning", "max_tokens", "temperature"]}]}}


def success():
    return {"id": "gen-fixture", "model": CONFIG["model"], "provider": "Venice",
        "choices": [{"finish_reason": "stop", "message": {"content": "fixture answer",
            "reasoning": "fixture reasoning", "reasoning_details": [{"type": "reasoning.text", "text": "fixture"}]}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 40, "cost": 0.01,
                  "completion_tokens_details": {"reasoning_tokens": 10}}}


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, body=None, status=200, failure=None, model_metadata=None, key_metadata=None,
                       messages=None, second_attempt=False, expected=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = Trace(root / "run", root / "workspace", secrets=["fixture-key"])
            ledger = Ledger(root / "budget.json")
            posts = []

            def handler(request):
                if request.method == "GET" and str(request.url).endswith("/key"):
                    return httpx.Response(200, json=key_metadata or {"data": {"limit": 50, "limit_reset": None,
                                                                                 "limit_remaining": 50}})
                if request.method == "GET":
                    return httpx.Response(200, json=model_metadata or endpoint())
                posts.append(json.loads(request.content))
                if failure:
                    raise failure("fixture timeout", request=request)
                return httpx.Response(status, json=body if body is not None else success(),
                                      headers={"x-request-id": "fixture-request", "retry-after": "5"})

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            async with OpenRouterSession(copy.deepcopy(CONFIG), "fixture-key", trace, ledger, "run", client) as session:
                if expected:
                    with self.assertRaises(RouterError) as caught:
                        await session.preflight()
                        await session.complete(messages or [{"role": "user", "content": "fixture"}])
                    self.assertEqual(caught.exception.category, expected)
                else:
                    await session.preflight()
                    self.assertEqual(await session.complete(messages or [{"role": "user", "content": "fixture"}]),
                                     "fixture answer")
                if second_attempt:
                    with self.assertRaises(RouterError):
                        await session.complete([{"role": "user", "content": "retry must be blocked"}])
            events_path = trace.root / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
            state = json.loads(ledger.path.read_text()) if ledger.path.exists() else {"requests": {}}
            return posts, events, state

    async def test_success_preserves_reasoning_usage_and_routing(self):
        posts, events, state = await self.exercise()
        self.assertEqual(len(posts), 1)
        self.assertFalse(posts[0]["stream"])
        self.assertFalse(posts[0]["provider"]["allow_fallbacks"])
        self.assertEqual(posts[0]["provider"]["order"], [CONFIG["provider"]])
        reasoning = next(e for e in events if e["kind"] == "reasoning_observation")
        self.assertEqual(reasoning["reasoning"], "fixture reasoning")
        self.assertTrue(reasoning["reasoning_details"])
        self.assertEqual(next(iter(state["requests"].values()))["status"], "settled")
        self.assertNotIn("fixture-key", json.dumps(events))

    async def test_http_errors_are_classified_and_never_retried(self):
        for status, category in [(400, "bad_request_or_context"), (401, "authentication"),
                                 (402, "insufficient_credit"), (403, "forbidden"), (408, "provider_timeout"),
                                 (429, "rate_limit"), (502, "provider_unavailable"), (503, "provider_unavailable")]:
            with self.subTest(status=status):
                posts, _, state = await self.exercise(body={"error": {"code": status}}, status=status,
                                                       expected=category, second_attempt=True)
                self.assertEqual(len(posts), 1)
                self.assertEqual(next(iter(state["requests"].values()))["status"], "reconciliation_required")

    async def test_timeout_preserves_unresolved_reservation(self):
        posts, _, state = await self.exercise(failure=httpx.ReadTimeout,
                                              expected="timeout_ambiguous_billing", second_attempt=True)
        self.assertEqual(len(posts), 1)
        self.assertEqual(next(iter(state["requests"].values()))["status"], "reconciliation_required")

    async def test_200_error_body_is_not_success(self):
        await self.exercise(body={"id": "gen-error", "error": {"code": 502}}, expected="provider_error")

    async def test_truncation_retains_raw_response_and_known_cost(self):
        body = success()
        body["choices"][0]["finish_reason"] = "length"
        _, events, state = await self.exercise(body=body, expected="truncated_output", second_attempt=True)
        self.assertTrue(any(e["kind"] == "openrouter_raw_response" for e in events))
        self.assertEqual(next(iter(state["requests"].values()))["cost_usd"], "0.01")

    async def test_empty_visible_content_is_rejected(self):
        body = success()
        body["choices"][0]["message"]["content"] = ""
        await self.exercise(body=body, expected="empty_content")

    async def test_missing_reasoning_is_explicit(self):
        body = success()
        body["choices"][0]["message"] = {"content": "fixture answer"}
        await self.exercise(body=body, expected="reasoning_not_returned")

    async def test_missing_cost_stops_subsequent_requests(self):
        body = success()
        del body["usage"]["cost"]
        posts, _, state = await self.exercise(body=body, expected="missing_cost", second_attempt=True)
        self.assertEqual(len(posts), 1)
        self.assertEqual(next(iter(state["requests"].values()))["status"], "reconciliation_required")

    async def test_returned_model_mismatch_stops_run(self):
        body = success()
        body["model"] = "other/model"
        await self.exercise(body=body, expected="returned_model_mismatch")

    async def test_preflight_rejects_unsupported_reasoning(self):
        metadata = endpoint()
        metadata["data"]["endpoints"][0]["supported_parameters"].remove("reasoning")
        posts, _, _ = await self.exercise(model_metadata=metadata, expected="preflight_unsupported_parameters")
        self.assertEqual(posts, [])

    async def test_preflight_rejects_price_changes(self):
        metadata = endpoint()
        metadata["data"]["endpoints"][0]["pricing"]["completion"] = "0.01"
        posts, _, _ = await self.exercise(model_metadata=metadata, expected="preflight_price_ceiling")
        self.assertEqual(posts, [])

    async def test_preflight_rejects_unlimited_or_resetting_key(self):
        for key, expected in [({"limit": None, "limit_remaining": 50}, "preflight_key_limit"),
                              ({"limit": 50, "limit_reset": "monthly", "limit_remaining": 50},
                               "preflight_recurring_key_limit")]:
            with self.subTest(key=key):
                posts, _, _ = await self.exercise(key_metadata={"data": key}, expected=expected)
                self.assertEqual(posts, [])

    async def test_unfunded_account_is_not_a_funded_fifty_dollar_key(self):
        posts, _, state = await self.exercise(key_metadata={"data": {
            "limit": 50, "limit_reset": None, "limit_remaining": 50, "is_free_tier": True}},
            expected="preflight_account_unfunded")
        self.assertEqual(posts, [])
        self.assertEqual(state["requests"], {})

    async def test_definitive_unfunded_rejection_is_settled_at_zero(self):
        body = {"error": {"code": 402,
            "message": "Insufficient credits. This account never purchased credits.",
            "metadata": {"limit_source": "openrouter_credits"}}}
        posts, events, state = await self.exercise(body=body, status=402,
                                                  expected="insufficient_credit", second_attempt=True)
        self.assertEqual(len(posts), 1)
        row = next(iter(state["requests"].values()))
        self.assertEqual(row["status"], "settled")
        self.assertEqual(row["cost_usd"], "0")
        self.assertTrue(any(e["kind"] == "unbilled_gateway_rejection" for e in events))

    async def test_oversized_context_sends_no_request(self):
        posts, _, _ = await self.exercise(messages=[{"role": "user", "content": "x" * 130000}],
                                           expected="context_precheck")
        self.assertEqual(posts, [])

    async def test_invalid_json_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Trace(Path(tmp) / "run", Path(tmp) / "workspace")
            ledger = Ledger(Path(tmp) / "budget.json")
            client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(502, text="bad gateway")))
            async with OpenRouterSession(CONFIG, "fixture", trace, ledger, "run", client) as session:
                session.context_length = 128000
                with self.assertRaises(RouterError) as caught:
                    await session.complete([{"role": "user", "content": "fixture"}])
                self.assertEqual(caught.exception.category, "invalid_json")


class BudgetTests(unittest.TestCase):
    def test_unresolved_requests_block_other_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "budget.json")
            request = ledger.reserve("first", "0.5", "5")
            with self.assertRaises(BudgetError):
                ledger.reserve("second", "0.5", "5")
            ledger.settle(request, "0.2", "gen-fixture")
            ledger.reserve("second", "0.5", "5")

    def test_total_and_per_run_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "budget.json")
            request = ledger.reserve("first", "49.9", "50")
            ledger.settle(request, "49.9", "gen-fixture")
            with self.assertRaises(BudgetError):
                ledger.reserve("second", "0.2", "5")
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "budget.json")
            with self.assertRaises(BudgetError):
                ledger.reserve("first", "5.01", "5")

    def test_bad_amounts_and_larger_authorization_are_rejected(self):
        for value in ("NaN", "Infinity", "-1", True, None):
            with self.subTest(value=value), self.assertRaises(BudgetError):
                money(value)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BudgetError):
                Ledger(Path(tmp) / "budget.json", "51")

    def test_corrupt_ledger_is_not_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.json"
            path.write_text("invalid")
            with self.assertRaises(BudgetError):
                Ledger(path).reserve("run", "1", "5")
            self.assertEqual(path.read_text(), "invalid")


class ResponseTests(unittest.TestCase):
    def test_generic_402_or_generation_response_stays_ambiguous(self):
        self.assertFalse(definite_unfunded_rejection(402, {"error": {"code": 402}}))
        body = {"error": {"code": 402, "message": "This account never purchased credits",
                          "metadata": {"limit_source": "openrouter_credits"}}}
        self.assertTrue(definite_unfunded_rejection(402, body))
        for field, value in [("id", "gen-existing"), ("choices", [{}]), ("usage", {"cost": 0.01})]:
            with self.subTest(field=field):
                self.assertFalse(definite_unfunded_rejection(402, {**body, field: value}))

    def test_malformed_choices_refusals_and_tools(self):
        for body in [[], {}, {"choices": []}, {"choices": [{"finish_reason": "content_filter"}]},
                     {"choices": [{"finish_reason": "stop", "message": {"refusal": "refused"}}]},
                     {"choices": [{"finish_reason": "stop", "message": {"tool_calls": [{}]}}]}]:
            with self.subTest(body=body), self.assertRaises(RouterError):
                parse_response(body)

    def test_model_router_and_closed_weight_configuration_are_rejected(self):
        for change in ({"model": "openrouter/auto"}, {"open_weights": False}, {"max_tokens": -1}):
            config = copy.deepcopy(CONFIG)
            config.update(change)
            with self.assertRaises(ValueError):
                validate_config(config)


if __name__ == "__main__":
    unittest.main()
