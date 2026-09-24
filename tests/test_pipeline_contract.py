"""Dataset reuse, representation controls, metadata, and metric definitions."""

import contextlib
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from judge.build_pair_dataset import augment
from judge.train_judge import save_prompt_metadata
from pipeline.config import load
from pipeline.metrics import summarize
from pipeline.representations import parse_equation, render, selftest
from pipeline.run import run, stage_data


class PipelineContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        self.path.write_text(json.dumps({"data": {"out_dir": str(self.root / "data")},
                                         "train": {"out_dir": str(self.root / "run")}}))
        self.cfg = load(self.path)

    def test_resolved_configuration_can_be_reloaded(self):
        saved = self.cfg.dump(str(self.root / "resolved"))
        self.assertEqual(load(saved).as_dict(), self.cfg.as_dict())

    def test_existing_adapter_preserves_its_configuration(self):
        directory = Path(self.cfg.train.out_dir)
        (directory / "adapter-final").mkdir(parents=True)
        original = directory / "resolved_config.yaml"
        original.write_text("original recipe")
        with self.assertRaises(FileExistsError):
            run(self.cfg, stage="train")
        self.assertEqual(original.read_text(), "original recipe")

    def test_changed_or_unknown_data_recipe_is_rejected(self):
        directory = Path(self.cfg.data.out_dir)
        directory.mkdir()
        (directory / "train.jsonl").write_text("{}\n")
        with patch("pipeline.run.subprocess.run") as process, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                stage_data(self.cfg, False)
        process.assert_not_called()

    def test_matching_data_recipe_reuses_complete_splits(self):
        directory = Path(self.cfg.data.out_dir)
        directory.mkdir()
        recipe = {"data": dict(self.cfg.data), "render": dict(self.cfg.render), "seed": self.cfg.seed}
        (directory / "pipeline_data_config.json").write_text(json.dumps(recipe))
        for split in ("train", "pairs_val", "classes_val", "test"):
            (directory / f"{split}.jsonl").write_text("{}\n")
        with patch("pipeline.run.subprocess.run") as process, contextlib.redirect_stdout(io.StringIO()):
            stage_data(self.cfg, False)
        process.assert_not_called()

    def test_infix_render_controls_reach_builder(self):
        eq = parse_equation("a * (b * a) = b")
        env = {"SDC_RENDER_KIND": "infix", "SDC_RENDER_RENAME": "False",
               "SDC_RENDER_FLIP": "False", "SDC_RENDER_OP": "@"}
        with patch.dict(os.environ, env):
            actual = augment(eq, random.Random(0))
        self.assertEqual(actual, "a @ (b @ a) = b")

    def test_renderers_preserve_grouping_and_variable_occurrences(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(selftest(), 0)

    def test_checkpoint_prompt_metadata(self):
        directory = self.root / "checkpoint-10"
        template = "Compare {a} with {b}\nRelation:"
        save_prompt_metadata(directory, template)
        metadata = json.loads((directory / "prompt_template.json").read_text())
        self.assertEqual(metadata["template"], template)
        self.assertEqual(metadata["labels"], ["equivalent", "weaker", "stronger", "incomparable"])

    def test_unknown_metrics_and_changed_label_order_are_rejected(self):
        self.cfg.eval["metrics"] = ["made-up"]
        with self.assertRaises(ValueError):
            run(self.cfg, dry_run=True)
        self.cfg.eval["metrics"] = ["accuracy"]
        self.cfg.prompt["labels"].reverse()
        with self.assertRaises(ValueError):
            run(self.cfg, dry_run=True)

    def test_false_equivalence_uses_non_equivalent_denominator(self):
        rows = [
            {"label": "weaker", "pred": "equivalent", "tier": "graph"},
            {"label": "stronger", "pred": "stronger", "tier": "graph"},
            {"label": "equivalent", "pred": "incomparable", "tier": "cross-node"},
        ]
        result = summarize(rows, ["accuracy", "false_equivalence", "missed_equivalence", "per_tier"])
        self.assertAlmostEqual(result["accuracy"], 1 / 3)
        self.assertEqual(result["false_equivalence"], {"errors": 1, "eligible": 2, "rate": 0.5})
        self.assertEqual(result["missed_equivalence"]["rate"], 1)
        self.assertEqual(result["per_tier"]["graph"]["n"], 2)
        self.assertNotIn("per_label", result)
        self.assertIsNone(summarize([], ["accuracy"])["accuracy"])
        with self.assertRaises(ValueError):
            summarize([{"label": "unknown", "pred": "equivalent"}], ["accuracy"])
