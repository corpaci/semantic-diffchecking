"""Offline interface tests. Synthetic logits do not validate trained weights."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from judge import Judge, LABELS
from pipeline.config import load
from pipeline.run import run, stage_eval


ROOT = Path(__file__).resolve().parents[1]


class Tensor:
    """Small NumPy-backed tensor double for exercising the scoring boundary."""

    def __init__(self, data):
        self.data = np.asarray(data)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            key = tuple(k.data if isinstance(k, Tensor) else k for k in key)
        return Tensor(self.data[key])

    def size(self, axis):
        return self.data.shape[axis]

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.data


def softmax(tensor, axis):
    x = tensor.data
    exp = np.exp(x - x.max(axis=axis, keepdims=True))
    return Tensor(exp / exp.sum(axis=axis, keepdims=True))


def synthetic_judge():
    """Pad positions favor the wrong label; only true final positions work."""
    judge = Judge.__new__(Judge)
    judge.device = "cpu"
    judge.template = "FIRST {a}\nSECOND {b}\nDECISION:"
    judge.label_ids = [2, 4, 6, 8]
    judge.torch = SimpleNamespace(
        no_grad=contextlib.nullcontext,
        tensor=lambda data, **kwargs: Tensor(data),
        arange=lambda n, **kwargs: Tensor(np.arange(n)),
        cat=lambda values: Tensor(np.concatenate([v.data for v in values])),
        empty=lambda shape, **kwargs: Tensor(np.empty(shape, dtype=np.float32)),
        softmax=softmax, float32=np.float32,
    )

    class Tokenizer:
        pad_token_id = 0

        def __call__(self, prompt, **kwargs):
            # Encodes the requested winning class and different sequence lengths.
            winner = int(prompt.split()[1])
            return SimpleNamespace(input_ids=[winner + 1] * (winner + 2))

    class Model:
        def __call__(self, input_ids, attention_mask):
            n, length = input_ids.data.shape
            logits = np.zeros((n, length, 10), dtype=float)
            logits[:, :, 2] = 100  # Poison all positions except each true last token.
            for row in range(n):
                last = int(attention_mask.data[row].sum()) - 1
                winner = int(input_ids.data[row, 0]) - 1
                logits[row, last] = 0
                logits[row, last, judge.label_ids[winner]] = 4
                logits[row, last, 9] = 1000  # Ignore non-label vocabulary logits.
            return SimpleNamespace(logits=Tensor(logits))

    judge.tok = Tokenizer()
    judge.model = Model()
    return judge


class JudgeInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.judge = synthetic_judge()

    def test_batch_uses_last_unpadded_position_and_only_label_tokens(self):
        pairs = [(str(i), "x = x") for i in range(4)]
        verdicts = self.judge.compare_many(iter(pairs), batch_size=3)
        self.assertEqual([v.label for v in verdicts], list(LABELS))
        for (a, b), verdict in zip(pairs, verdicts):
            self.assertEqual((verdict.text_a, verdict.text_b), (a, b))
            self.assertAlmostEqual(sum(verdict.probs.values()), 1)
            self.assertGreater(verdict.confidence, 0.9)
            self.assertEqual(json.loads(json.dumps(verdict.to_dict()))["label"], verdict.label)

    def test_function_call_and_compare_reuse_the_model(self):
        model = self.judge.model
        self.assertEqual(self.judge("1", "x = x"), self.judge.compare("1", "x = x"))
        self.assertIs(self.judge.model, model)

    def test_prompt_preserves_saved_template(self):
        self.assertEqual(self.judge.format_prompt("a", "b"), "FIRST a\nSECOND b\nDECISION:")

    def test_empty_batches_and_ranking(self):
        self.assertEqual(self.judge.probs([]).shape, (0, 4))
        self.assertEqual(self.judge.compare_many([]), [])
        self.assertEqual(self.judge.rank("x = x", []), [])

    def test_invalid_inputs_fail_before_inference(self):
        for size in [0, -1, 1.5, True]:
            with self.assertRaises(ValueError):
                self.judge.probs([], batch_size=size)
        for pairs in [[("", "x")], [(1, "x")], ["ab"], [("x",)]]:
            with self.assertRaises(ValueError):
                self.judge.probs(pairs)


class PipelineInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config.json"
        self.out = Path(self.temp.name) / "run"
        self.config_path.write_text(json.dumps({
            "name": "interface-test", "train": {"out_dir": str(self.out)},
            "eval": {"splits": ["test"]},
        }))

    def test_dry_run_from_path_writes_and_launches_nothing(self):
        with patch("pipeline.run.subprocess.run") as process, contextlib.redirect_stdout(io.StringIO()):
            result = run(self.config_path, dry_run=True)
        process.assert_not_called()
        self.assertFalse(self.out.exists())
        self.assertEqual(result["stages"], ["data", "train", "eval"])
        self.assertTrue(result["dry_run"])

    def test_config_object_is_revalidated(self):
        config = load(self.config_path)
        config.render["kind"] = "invalid"
        with self.assertRaises(SystemExit):
            run(config, dry_run=True)
        self.assertFalse(self.out.exists())

    def test_bad_stage_and_unknown_keys_fail_without_writes(self):
        with self.assertRaises(ValueError):
            run(self.config_path, stage="typo")
        self.config_path.write_text('{"train": {"typo": 5}}')
        with self.assertRaises(KeyError):
            run(self.config_path, dry_run=True)
        self.assertFalse(self.out.exists())

    def test_existing_adapter_allows_preview_but_prevents_training(self):
        (self.out / "adapter-final").mkdir(parents=True)
        with patch("pipeline.run.subprocess.run") as process, contextlib.redirect_stdout(io.StringIO()):
            run(self.config_path, stage="train", dry_run=True)
            with self.assertRaises(FileExistsError):
                run(self.config_path, stage="train")
        process.assert_not_called()

    def test_stage_failure_stops_later_stages(self):
        error = subprocess.CalledProcessError(1, ["dataset-builder"])
        with patch("pipeline.run.stage_data", side_effect=error), \
             patch("pipeline.run.stage_train") as train, \
             patch("pipeline.run.stage_eval") as evaluate, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                run(self.config_path)
        train.assert_not_called()
        evaluate.assert_not_called()

    def test_evaluation_failure_is_not_silently_reported_as_success(self):
        (self.out / "adapter-final").mkdir(parents=True)
        error = subprocess.CalledProcessError(1, ["judge"])
        with patch("pipeline.run.subprocess.run", side_effect=error) as process, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                stage_eval(load(self.config_path), dry=False)
        self.assertTrue(process.call_args.kwargs["check"])
        self.assertFalse((self.out / "eval_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
