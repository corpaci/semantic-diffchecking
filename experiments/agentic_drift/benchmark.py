"""Run original ClassEval tests. Invoke only inside an isolated container."""
import argparse
import hashlib
import io
import json
import types
import unittest
from pathlib import Path


def evaluate_class(dataset, task_id, source=None, reference=False, checks=None):
    dataset = Path(dataset)
    provenance = json.loads(dataset.with_name("provenance.json").read_text())
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != provenance["sha256"]:
        raise ValueError("ClassEval dataset checksum mismatch")
    record = next(r for r in json.loads(dataset.read_text()) if r["task_id"] == task_id)
    code = record["solution_code"] if reference else Path(source).read_text()
    module = types.ModuleType("benchmark_candidate")
    exec(compile("\n".join(record["import_statement"]), "benchmark_imports", "exec"), module.__dict__)
    exec(compile(code, "solution.py", "exec"), module.__dict__)
    exec(compile(record["test"], "withheld_tests.py", "exec"), module.__dict__)
    if checks:
        exec(compile(Path(checks).read_text(), "independent_requirement_checks.py", "exec"), module.__dict__)

    class Results(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.test_statuses = {}

        def addSuccess(self, test):
            super().addSuccess(test)
            self.test_statuses[test.id()] = "pass"

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.test_statuses[test.id()] = "fail"

        def addError(self, test, err):
            super().addError(test, err)
            self.test_statuses[test.id()] = "error"

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.test_statuses[test.id()] = "skip"

    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=Results).run(suite)
    requirements = {}
    for name in dir(module):
        klass = getattr(module, name)
        if not isinstance(klass, type) or not issubclass(klass, unittest.TestCase):
            continue
        for method_name in unittest.defaultTestLoader.getTestCaseNames(klass):
            method = getattr(klass, method_name)
            for requirement_id in getattr(method, "requirement_ids", []):
                test_id = f"{klass.__module__}.{klass.__qualname__}.{method_name}"
                requirements.setdefault(requirement_id, {})[test_id] = result.test_statuses.get(test_id, "unassessed")
    requirement_results = {key: {"tests": tests, "status": "pass" if all(s == "pass" for s in tests.values())
                               else "fail" if "fail" in tests.values() else "error_or_unassessed"}
                           for key, tests in requirements.items()}
    return {"task_id": task_id, "dataset_commit": provenance["commit"],
            "candidate": "reference" if reference else "generated",
            "tests_run": result.testsRun, "tests": result.test_statuses,
            "all_pass": result.wasSuccessful() and result.testsRun > 0,
            "requirements": requirement_results,
            "evidence": "original_finite_tests_not_semantic_equivalence",
            "prose_semantics": "unassessed"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--checks", help="Withheld independent requirement checks; mount only during evaluation")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--source")
    group.add_argument("--reference", action="store_true")
    a = p.parse_args()
    if not Path("/.dockerenv").exists():
        p.error("Run this evaluator in a credential-free Docker container with --network none")
    from .trace import dump
    try:
        result = evaluate_class(a.dataset, a.task, a.source, a.reference, a.checks)
    except Exception as error:
        result = {"task_id": a.task, "status": "invalid_candidate_or_evaluation_error",
                  "exception_type": type(error).__name__, "all_pass": False,
                  "requirements": {}, "note": "No behavioral requirement labels are inferred from import or syntax failure."}
    dump(a.out, result)
    print(json.dumps({k: v for k, v in result.items() if k != "tests"}))


if __name__ == "__main__":
    main()
