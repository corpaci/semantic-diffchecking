"""Validate the BankAccount instrument with reference code and controlled mutations."""
import argparse
import ast
import json
from pathlib import Path

from .benchmark import evaluate_class
from .trace import dump

MUTATIONS = {
    "rejected_deposit_changes_balance": ("deposit", "R03", '''
def deposit(self, amount):
    if amount < 0:
        self.balance = 0
        raise ValueError("Invalid amount")
    self.balance += amount
    return self.balance
'''),
    "rejected_withdrawal_changes_balance": ("withdraw", "R06", '''
def withdraw(self, amount):
    if amount < 0:
        raise ValueError("Invalid amount")
    if amount > self.balance:
        self.balance = 0
        raise ValueError("Insufficient balance.")
    self.balance -= amount
    return self.balance
'''),
    "balance_read_changes_state": ("view_balance", "R07", '''
def view_balance(self):
    previous = self.balance
    self.balance += 1
    return previous
'''),
    "transfer_does_not_credit_recipient": ("transfer", "R08", '''
def transfer(self, other_account, amount):
    self.withdraw(amount)
'''),
}


def validate(dataset, checks, out):
    if not Path("/.dockerenv").exists():
        raise RuntimeError("Run code evaluation in the isolated container")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    reference = evaluate_class(dataset, "ClassEval_8", reference=True, checks=checks)
    if not reference["all_pass"] or len(reference["requirements"]) != 13:
        raise AssertionError("Reference does not satisfy all mapped requirements")
    record = next(r for r in json.loads(Path(dataset).read_text()) if r["task_id"] == "ClassEval_8")
    report = {"kind": "instrument_validation_not_agent_results", "reference": reference, "mutations": {}}
    for name, (method_name, requirement_id, code) in MUTATIONS.items():
        tree = ast.parse(record["solution_code"])
        klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BankAccount")
        replacement = ast.parse(code).body[0]
        klass.body = [replacement if isinstance(n, ast.FunctionDef) and n.name == method_name else n for n in klass.body]
        source = out / (name + ".py")
        source.write_text(ast.unparse(tree) + "\n")
        original = evaluate_class(dataset, "ClassEval_8", source=source)
        augmented = evaluate_class(dataset, "ClassEval_8", source=source, checks=checks)
        if augmented["requirements"][requirement_id]["status"] != "fail":
            raise AssertionError(f"Expected requirement failure was not detected: {name}")
        report["mutations"][name] = {"expected_requirement_failure": requirement_id,
            "original_tests_all_pass": original["all_pass"],
            "failed_requirements": [k for k, v in augmented["requirements"].items() if v["status"] != "pass"],
            "extended_result": augmented}
    dump(out / "report.json", report)
    print(json.dumps({"reference_tests": reference["tests_run"], "requirements": len(reference["requirements"]),
        "detected_mutations": len(report["mutations"]),
        "mutations_missed_by_original_tests": sum(r["original_tests_all_pass"] for r in report["mutations"].values())}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--checks", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    validate(a.dataset, a.checks, a.out)
