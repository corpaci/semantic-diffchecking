"""Validation uses authored fixtures and fake transport, never paid requests."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .etp import Oracle, UnsupportedCode, decode, pointwise_probe
from .tasks import all_tasks, ordinary_tasks
from .worker import evaluate_source
from . import study


class Fixtures(unittest.TestCase):
    def test_references_and_mutations(self):
        for task in ordinary_tasks().values():
            with self.subTest(task=task["id"]):
                report = evaluate_source(task["reference"], task)
                self.assertTrue(report["all_pass"])
                covered = {r for row in report["checks"] for r in row["requirements"]}
                self.assertEqual(covered, set(task["requirements"]))
                for mutant in task["mutations"]:
                    self.assertNotEqual(mutant, task["reference"])
                    report = evaluate_source(mutant, task)
                    self.assertFalse(report["all_pass"])
                    self.assertTrue(any(c["status"] == "fail" for c in report["checks"]))

    def test_directional_labels(self):
        task = ordinary_tasks()["permissions"]
        weak = evaluate_source("def permitted(role, action, owner, locked):\n    return True\n", task)
        strong = evaluate_source("def permitted(role, action, owner, locked):\n    return False\n", task)
        self.assertIn("weaker_observed", {c["category"] for c in weak["checks"]})
        self.assertIn("stronger_observed", {c["category"] for c in strong["checks"]})

    def test_interface_and_execution_separate(self):
        task = ordinary_tasks()["permissions"]
        renamed = task["reference"].replace("owner", "is_owner")
        result = evaluate_source(renamed, task)
        self.assertFalse(result["interface_pass"])
        self.assertTrue(all(r == "pass" for r in result["requirements"].values()))
        blocked = evaluate_source("raise NameError('broken')", task)
        self.assertEqual(blocked["status"], "execution_failure")
        self.assertEqual(set(blocked["requirements"].values()), {"blocked"})


class Decoder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = Oracle(study.REPO / "oracle", study.DATA)

    @classmethod
    def tearDownClass(cls):
        cls.oracle.close()

    def test_aliases_and_swapped_equality(self):
        original = decode("def law(op, x, y, z):\n    return op(x, y) == x\n")
        refactor = decode('def law(op, x, y, z):\n    """Law."""\n    left = op(x, y)\n    right = x\n    return right == left\n')
        self.assertEqual(self.oracle.compare(original, refactor)["label"], "equal")
        self.assertEqual(pointwise_probe(original, refactor)["status"], "passed_finite_probes")

    def test_rejects_non_equation_code_without_executing(self):
        bad = ["import os\n", "def law(op,x,y,z):\n return True\n",
               "def law(op,x,y,z):\n x = y\n return x == y\n",
               "def law(op,x,y,z):\n return x == y == z\n",
               "def law(op,x,y,z):\n return op(x,y) != x\n",
               "def law(op,x,y,z):\n return (lambda: x)() == y\n",
               "def law(op,x,y,z):\n a = x\n a = y\n return a == x\n",
               "def law(op: print('no'),x,y,z):\n return x == y\n"]
        for source in bad:
            with self.subTest(source=source), self.assertRaises(UnsupportedCode):
                decode(source)

    def test_formal_directions_and_pointwise_distinction(self):
        self.assertEqual(self.oracle.compare("x * y = x", "x * x = x")["label"], "weaker")
        self.assertEqual(self.oracle.compare("x * x = x", "x * y = x")["label"], "stronger")
        self.assertEqual(self.oracle.compare("x * y = x", "x * y = y")["label"], "incomparable")
        # Bijective variable renaming preserves a universally quantified identity,
        # but need not preserve a Python function's result for a fixed assignment.
        a, b = "x * y = x", "y * x = y"
        self.assertEqual(self.oracle.compare(a, b)["label"], "equal")
        self.assertEqual(pointwise_probe(a, b)["status"], "counterexample")

    def test_all_etp_references_map(self):
        for task in all_tasks().values():
            if task["track"] == "etp":
                eq = decode(task["reference"])
                self.assertEqual(self.oracle.compare(eq, eq)["label"], "equal")


class Protocol(unittest.TestCase):
    def test_long_schedule_balances_repetitions_and_retains_every_hop(self):
        from collections import Counter
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "targeted_long")
            plan = study.load_plan(out)
            self.assertEqual(plan["hops"], 20)
            self.assertEqual(plan["checkpoints"], list(range(21)))
            self.assertEqual(len(plan["rows"]), 36)
            self.assertEqual(plan["max_paid_calls"], 720)
            cells = Counter((r["task"], r["family"], r["condition"]) for r in plan["rows"])
            self.assertEqual(len(cells), 12)
            self.assertEqual(set(cells.values()), {3})
            self.assertTrue(all(c["max_calls"] == 20 for c in plan["configs"].values()))
            task = all_tasks()["permissions"]
            for hop in (2, 3, 19, 20):
                prompt = study.messages(task, "PREVIOUS", "none", hop, [], study.TARGETED)
                self.assertEqual(len(prompt), 2)
                self.assertIn(study.OBJECTIVES["permissions"][(hop-1)%2], prompt[0]["content"])

    def test_targeted_two_hop_schedule_and_condition_matching(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "targeted")
            plan = study.load_plan(out)
            self.assertEqual(plan["hops"], 2)
            self.assertEqual(plan["max_paid_calls"], 24)
            self.assertEqual(plan["prompt_policy"], study.TARGETED)
            for task_id in ("permissions", "etp_associativity"):
                task = all_tasks()[task_id]
                for hop in (1, 2):
                    baseline = study.messages(task, task["reference"], "none", hop, [], study.TARGETED)
                    reminder = study.messages(task, task["reference"], "every", hop, [], study.TARGETED)
                    self.assertEqual(baseline[0], reminder[0])
                    self.assertEqual(baseline[-1], reminder[-1])
                    self.assertIn(study.OBJECTIVES[task_id][hop-1], baseline[0]["content"])
                    self.assertEqual(len(baseline), 2)
                    self.assertEqual(len(reminder), 3)

    def test_structural_compliance_separate_from_semantics(self):
        tasks = all_tasks()
        permission_expanded = tasks["permissions"]["reference"].replace(
            'return role == "admin" or (role == "editor" and action == "write" and owner)',
            'if role == "admin":\n        return True\n    if role == "editor" and action == "write" and owner:\n        return True\n    return False')
        self.assertTrue(study.objective_met(permission_expanded, "permissions", 1))
        self.assertFalse(study.objective_met(tasks["permissions"]["reference"], "permissions", 1))
        self.assertTrue(study.objective_met(tasks["permissions"]["reference"], "permissions", 2))
        eq_expanded = "def law(op, x, y, z):\n    left = op(op(x, y), z)\n    right = op(x, op(y, z))\n    return left == right\n"
        self.assertTrue(study.objective_met(eq_expanded, "etp_associativity", 1))
        self.assertFalse(study.objective_met(eq_expanded, "etp_associativity", 2))
        self.assertTrue(study.objective_met(tasks["etp_associativity"]["reference"], "etp_associativity", 2))
        # Incorrect argument order can satisfy structure while changing the law.
        wrong = eq_expanded.replace('op(y, z)', 'op(z, y)')
        self.assertTrue(study.objective_met(wrong, "etp_associativity", 1))
        self.assertNotEqual(decode(wrong), decode(eq_expanded))

    def test_context_isolation_and_sparse_reminder(self):
        task = all_tasks()["etp_associativity"]
        source = "PREVIOUS_ARTIFACT"
        baseline = study.messages(task, source, "none", 2, [5])
        sparse_before = study.messages(task, source, "sparse", 4, [5])
        sparse_at = study.messages(task, source, "sparse", 5, [5])
        self.assertEqual(baseline, sparse_before)
        self.assertEqual(len(baseline), 2)
        self.assertEqual(len(sparse_at), 3)
        self.assertNotIn(task["reference"], json.dumps(baseline))
        self.assertIn(task["reference"], sparse_at[1]["content"])
        self.assertNotIn("rows", json.dumps(sparse_at))

    def test_format_extracts_one_block_preserves_syntax_failures(self):
        self.assertEqual(study.extract("Note\n```python\nnot python ???\n```"), "not python ???\n")
        for answer in ["x = 1", "```python\nx=1\n```\n```python\nx=2\n```", "```python\n\n```"]:
            with self.assertRaises(ValueError):
                study.extract(answer)

    def test_frozen_plan_detects_task_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "integration")
            plan = study.load_plan(out)
            self.assertEqual(len(plan["rows"]), 12)
            self.assertEqual(plan["max_paid_calls"], 12)
            (out / "tasks" / "permissions" / "reference.py").write_text("changed")
            with self.assertRaisesRegex(ValueError, "Frozen task"):
                study.load_plan(out)

    def test_pending_request_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "integration")
            plan = study.load_plan(out)
            plan["calibration"] = dict(path=str(out / "plan.json"), sha256=study.digest(out / "plan.json"))
            chain = out / "chains" / plan["rows"][0]["id"]
            chain.mkdir(parents=True)
            (chain / "status.json").write_text(json.dumps(dict(status="request_pending")))
            with patch.object(study, "load_plan", return_value=plan), patch.dict("os.environ", {"DRIFT_API_KEY": "fake-not-sent"}), self.assertRaisesRegex(ValueError, "No automatic retry"):
                asyncio.run(study.generate(out))

    def test_generation_resume_and_no_test_feedback(self):
        requests = []

        class FakeSession:
            def __init__(self, *args):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def preflight(self):
                pass
            async def complete(self, prompt):
                requests.append(prompt)
                return prompt[-1]["content"].split("Previous code:\n", 1)[1]

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "study"
            study.prepare(out, "targeted")
            plan = study.load_plan(out)
            plan["calibration"] = dict(path=str(out / "plan.json"), sha256=study.digest(out / "plan.json"))
            task_path = out / "tasks" / "permissions" / "task.json"
            task = json.loads(task_path.read_text())
            task["rows"][0]["private_note"] = "PRIVATE_EVALUATION_SENTINEL"
            task_path.write_text(json.dumps(task))
            with patch.object(study, "load_plan", return_value=plan), patch.object(study, "Ledger"), patch.object(study, "OpenRouterSession", FakeSession), patch.dict("os.environ", {"DRIFT_API_KEY": "fake-not-sent"}):
                asyncio.run(study.generate(out))
                self.assertEqual(len(requests), 24)
                asyncio.run(study.generate(out))
                self.assertEqual(len(requests), 24)
            for row in plan["rows"]:
                status = json.loads((out / "chains" / row["id"] / "status.json").read_text())
                self.assertEqual(status["status"], "complete")
                self.assertEqual(status["completed_hops"], 2)
            self.assertFalse(any("PRIVATE_EVALUATION_SENTINEL" in json.dumps(p) for p in requests))


if __name__ == "__main__":
    unittest.main()
