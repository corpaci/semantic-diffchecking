"""Offline container evaluator. Never call this on untrusted code on the host."""
import ast
import copy
import inspect
import json
import resource
import sys
from pathlib import Path

if __package__:
    from .tasks import ordinary_tasks
else:
    from tasks import ordinary_tasks


def evaluate_source(source, task):
    namespace = {}
    try:
        exec(compile(source, "candidate.py", "exec"), namespace)
        name = task["signature"].split("(")[0]
        function = namespace[name]
        expected_args = [s.strip() for s in task["signature"].split("(")[1].rstrip(")").split(",")]
        parameters = inspect.signature(function).parameters
        interface = list(parameters) == expected_args and all(
            p.default is inspect.Parameter.empty and p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            for p in parameters.values())
    except BaseException as error:
        return dict(status="execution_failure", exception_type=type(error).__name__, checks=[],
                    all_pass=False, requirements={r: "blocked" for r in task["requirements"]})
    checks = []
    for index, row in enumerate(task["rows"]):
        args = copy.deepcopy(row["args"])
        before = copy.deepcopy(args)
        actual, error = None, None
        try:
            actual = function(*args)
        except BaseException as exc:
            error = [type(exc).__name__, str(exc)]
        expected_error = row["raises"]
        correct = (error == expected_error if expected_error else error is None and
                   type(actual) is type(row["expected"]) and actual == row["expected"])
        category = None
        if not correct:
            if row["kind"] == "admission" and error is None and type(actual) is bool:
                category = "weaker_observed" if actual else "stronger_observed"
            elif row["kind"] == "transition" and expected_error and error is None:
                category = "weaker_observed"
            elif row["kind"] == "transition" and not expected_error and error:
                category = "stronger_observed"
            else:
                category = "wrong_output_or_exception"
        checks.append(dict(check_id=f"C{index:05}", requirements=row["requirements"],
                           status="pass" if correct else "fail", category=category,
                           args=row["args"], expected=row["expected"], expected_exception=expected_error,
                           actual=repr(actual)[:300], exception=error))
        if task["id"] == "bookings":
            checks.append(dict(check_id=f"C{index:05}-state", requirements=["R04"],
                               status="pass" if args == before else "fail",
                               category=None if args == before else "state_mutation"))
    requirements = {r: "pass" if all(c["status"] == "pass" for c in checks if r in c["requirements"])
                    else "fail" for r in task["requirements"]}
    return dict(status="evaluated", interface_pass=interface, checks=checks,
                requirements=requirements, all_pass=interface and all(v == "pass" for v in requirements.values()))


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    task = ordinary_tasks()[sys.argv[1]]
    source = Path("/candidate/solution.py").read_text()
    try:
        ast.parse(source)
    except SyntaxError:
        result = dict(status="syntax_failure", all_pass=False, checks=[],
                      requirements={r: "blocked" for r in task["requirements"]})
    else:
        result = evaluate_source(source, task)
    # The container has no host writable mounts or network, and no API credentials.
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
