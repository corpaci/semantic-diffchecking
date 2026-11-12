"""Checks for the experimental instrument, not model-quality claims."""
import json
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path

from .__main__ import calibrate, fetch_classeval
from .trace import Trace, dump


class HarnessTests(unittest.TestCase):
    def test_failed_checkpoint_replace_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.json"
            dump(path, {"completed_hops": 1})
            with patch("experiments.agentic_drift.trace.os.replace", side_effect=OSError("fixture interruption")):
                with self.assertRaises(OSError):
                    dump(path, {"completed_hops": 2})
            self.assertEqual(json.loads(path.read_text()), {"completed_hops": 1})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_dataset_fetch_uses_case_snapshot_instead_of_changing_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "dataset"
            body = json.dumps([dict(task_id="ClassEval_8", skeleton="class BankAccount: pass")]).encode()
            with patch("experiments.agentic_drift.__main__.urlopen", return_value=BytesIO(body)) as request:
                fetch_classeval(out)
            provenance = json.loads((out / "provenance.json").read_text())
            case = Path(__file__).parent / "cases/bankaccount_v1/requirements.json"
            self.assertEqual(provenance["commit"], json.loads(case.read_text())["source_commit"])
            self.assertIn(provenance["commit"], request.call_args.args[0].full_url)
            self.assertEqual(request.call_count, 1)

    def test_reference_and_targeted_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "calibration"
            calibrate(root)
            result = json.loads((root / "calibration.json").read_text())
            for task in result["tasks"].values():
                self.assertTrue(task["reference"]["all_pass"])
                self.assertFalse(task["mutation"]["all_pass"])
                lost = task["known_mutated_obligation"]
                self.assertEqual(task["mutation"]["checks"][lost]["status"], "fail")

    def test_snapshots_preserve_versions_and_redact_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = Trace(root / "run", root / "workspace", secrets=["test-secret"])
            source = trace.workspace / "solution.py"
            source.write_text("first test-secret")
            first = trace.snapshot("first")
            source.write_text("second")
            second = trace.snapshot("second")
            digest = first["solution.py"]["sha256"]
            self.assertNotEqual(digest, second["solution.py"]["sha256"])
            self.assertEqual((trace.root / "blobs" / digest).read_text(), "first [REDACTED]")
            trace.event("prompt", text="test-secret")
            self.assertNotIn("test-secret", (trace.root / "events.jsonl").read_text())

    def test_external_symlinks_do_not_enter_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.txt"
            outside.write_text("private")
            trace = Trace(root / "run", root / "workspace")
            (trace.workspace / "link.txt").symlink_to(outside)
            self.assertEqual(trace.snapshot("links"), {})


if __name__ == "__main__":
    unittest.main()
