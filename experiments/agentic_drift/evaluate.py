"""Independent requirement checks. Execute generated code only inside Docker."""
import importlib.util
from pathlib import Path


def evaluate(task_id, source):
    spec = importlib.util.spec_from_file_location("candidate", Path(source))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = {}

    def check(name, fn):
        try:
            passed = bool(fn())
            checks[name] = {"status": "pass" if passed else "fail"}
        except Exception as error:
            checks[name] = {"status": "error", "exception_type": type(error).__name__}

    def unchanged(fn, values, *args):
        before = values.copy()
        fn(values, *args)
        return values == before

    if task_id == "stable_unique":
        fn = module.stable_unique
        check("unique", lambda: fn([3, 1, 3, 2, 1]).count(3) == 1
              and set(fn([3, 1, 3, 2, 1])) == {1, 2, 3})
        check("first_occurrence_order", lambda: fn([3, 1, 3, 2, 1]) == [3, 1, 2]
              and fn([-1, 2, -1, 0]) == [-1, 2, 0])
        check("input_unchanged", lambda: unchanged(fn, [3, 1, 3]))
        check("empty_input", lambda: fn([]) == [])
    elif task_id == "bounded_sum":
        fn = module.bounded_sum
        check("lower_inclusive", lambda: fn([2, 3], 2, 4) == 5)
        check("upper_exclusive", lambda: fn([2, 4], 2, 4) == 2 and fn([2], 2, 2) == 0)
        check("input_unchanged", lambda: unchanged(fn, [3, 1, 3], 1, 4))
        check("empty_input", lambda: fn([], 0, 10) == 0)
    elif task_id == "first_index":
        fn = module.first_index
        check("first_match", lambda: fn([4, 2, 4], 4) == 0 and fn([1, 2, 2], 2) == 1)
        check("absent_minus_one", lambda: fn([1, 2], 8) == -1)
        check("input_unchanged", lambda: unchanged(fn, [4, 2, 4], 4))
        check("empty_input", lambda: fn([], 3) == -1)
    else:
        raise ValueError(f"Unsupported calibration task: {task_id}")
    return {"task_id": task_id, "checks": checks,
            "all_pass": all(x["status"] == "pass" for x in checks.values()),
            "evidence": "finite_behavioral_checks_not_equivalence_proof"}
