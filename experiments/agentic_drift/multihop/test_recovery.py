"""Recovery tests use temporary ledgers and recorded fixtures, never network calls."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ..budget import BudgetError, Ledger
from ..openrouter import RouterError
from ..trace import Trace, dump
from . import study
from .recovery import recover


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / "study"
        study.prepare(self.out, "integration")
        self.plan = study.load_plan(self.out)
        self.plan["ledger"] = str(Path(self.temp.name) / "spend.json")
        self.row = self.plan["rows"][0]
        self.chain = self.out / "chains" / self.row["id"]
        self.trace = Trace(self.chain / "transport", self.chain / "workspace")
        self.ledger = Ledger(self.plan["ledger"])
        self.request = self.ledger.reserve(self.plan["study_id"] + ":" + self.row["id"], "1", "5")
        source = self.out / "tasks" / self.row["task"] / "reference.py"
        (self.chain / "hop-000.py").write_bytes(source.read_bytes())
        prompt = study.messages(study.all_tasks()[self.row["task"]], source.read_text(), "none", 1, [])
        dump(self.chain / "hop-001-input.json", prompt)
        config = self.plan["configs"][self.row["family"]]
        self.trace.event("openrouter_request", reservation_id=self.request, reserved_usd="1",
                         payload=dict(model=config["model"], max_tokens=config["max_tokens"], messages=prompt))
        self.trace.event("openrouter_error", reservation_id=self.request,
                         category="RemoteProtocolError", generation_id=None)
        self.ledger.unresolved(self.request, "RemoteProtocolError")
        dump(self.chain / "status.json", dict(status="request_stopped", completed_hops=0, attempted_hop=1,
             artifact_hashes={"hop-000.py": study.digest(source)}))

    def recover(self, execute=False):
        recover(self.out, self.plan, self.row["id"], self.request, execute)

    def test_inspection_is_read_only_and_apply_retains_unknown_charge(self):
        original = self.ledger.path.read_bytes()
        self.recover()
        self.assertEqual(self.ledger.path.read_bytes(), original)
        self.recover(True)
        state = json.loads(self.ledger.path.read_text())
        self.assertEqual(state["requests"][self.request]["status"], "billing_hold")
        self.assertIsNone(state["requests"][self.request]["cost_usd"])
        self.assertEqual(json.loads((self.chain / "status.json").read_text())["status"], "between_hops")
        self.assertEqual((self.out / "recovery" / self.request / "original-spend.json").read_bytes(), original)
        with self.assertRaises(BudgetError):
            self.ledger.reserve(state["requests"][self.request]["run_id"], "5", "5")
        with self.assertRaises(ValueError):
            self.recover(True)  # Never reset a later attempt.

    def test_response_or_changed_checkpoint_blocks_retry(self):
        (self.chain / "hop-001-response.txt").write_text("saved")
        with self.assertRaisesRegex(ValueError, "saved artifact"):
            self.recover(True)
        (self.chain / "hop-001-response.txt").unlink()
        (self.chain / "hop-000.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "checkpoint changed"):
            self.recover(True)

    def test_wrong_request_and_other_unresolved_billing_block_retry(self):
        with self.assertRaises(ValueError):
            recover(self.out, self.plan, self.row["id"], "wrong", True)
        with self.ledger.edit() as state:
            state["requests"]["other"] = dict(status="pending")
        with self.assertRaises(BudgetError):
            self.recover(True)

    def test_settled_billing_cannot_be_replaced_with_a_hold(self):
        self.ledger.settle(self.request, "0.1", "fixture-generation")
        with self.assertRaises(BudgetError):
            self.ledger.hold(self.request, {"fixture": True})


class ContinuationTests(unittest.TestCase):
    def test_settled_output_limit_skips_chain_without_retry_and_resumes_other_chains(self):
        calls = []

        class FakeSession:
            def __init__(self, config, key, trace, ledger, run_id):
                self.config, self.trace, self.ledger, self.run_id = config, trace, ledger, run_id
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def preflight(self): pass
            async def complete(self, prompt):
                calls.append(prompt)
                if len(calls) == 1:
                    reservation = self.ledger.reserve(self.run_id, "1", "5")
                    self.trace.event("openrouter_request", reservation_id=reservation,
                                     payload=dict(max_tokens=self.config["max_tokens"]))
                    self.trace.event("openrouter_raw_response", reservation_id=reservation, http_status=200,
                                     body=dict(model=self.config["model"], id="fixture-generation",
                                               choices=[dict(finish_reason="length")], usage=dict(cost="0.1")))
                    self.ledger.settle(reservation, "0.1", "fixture-generation")
                    raise RouterError("truncated_output")
                return prompt[-1]["content"].split("Previous code:\n", 1)[1]

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "integration")
            plan = study.load_plan(out)
            plan["ledger"] = str(Path(temporary) / "spend.json")
            plan["calibration"] = dict(path=str(out / "plan.json"), sha256=study.digest(out / "plan.json"))
            with patch.object(study, "load_plan", return_value=plan), patch.object(study, "OpenRouterSession", FakeSession), patch.dict("os.environ", {"DRIFT_API_KEY": "test-only-secret-unused"}):
                asyncio.run(study.generate(out))
                asyncio.run(study.generate(out))
            self.assertEqual(len(calls), 12)
            states = [json.loads((out / "chains" / row["id"] / "status.json").read_text())["status"] for row in plan["rows"]]
            self.assertEqual(states.count("output_limit"), 1)
            self.assertEqual(states.count("complete"), 11)

    def test_summary_counts_absent_outputs_separately_from_failed_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "integration")
            plan = study.load_plan(out)
            row = plan["rows"][0]
            dump(out / "evaluations.json", dict(records=[dict(**row, hop=1, track="ordinary",
                 artifact_sha256="fixture", result=dict(status="syntax_failure", all_pass=False))]))
            study.summarize(out)
            groups = json.loads((out / "summary.json").read_text())["groups"]
            present = next(g for g in groups if g["family"] == row["family"] and g["condition"] == row["condition"] and g["track"] == "ordinary" and g["hop"] == 1)
            self.assertEqual((present["evaluated"], present["all_checks_pass"], present["unavailable"]), (1, 0, 0))
            self.assertTrue(any(g["unavailable"] == g["planned"] > 0 for g in groups))


if __name__ == "__main__":
    unittest.main()
