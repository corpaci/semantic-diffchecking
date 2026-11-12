"""Persistent spending reservations. Unanswered requests require manual reconciliation."""
import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path


class BudgetError(RuntimeError):
    pass


def accounted(row):
    if row["status"] == "settled":
        return money(row["cost_usd"])
    if row["status"] == "billing_hold" and row.get("cost_usd") is None:
        return money(row["reserved_usd"])
    raise BudgetError("An unresolved request exists. Reconcile or explicitly hold it before continuing.")


def money(value):
    if isinstance(value, bool):
        raise BudgetError("Boolean is not a monetary amount")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BudgetError("Invalid monetary amount") from None
    if not result.is_finite() or result < 0:
        raise BudgetError("Monetary amounts must be finite and nonnegative")
    return result


class Ledger:
    def __init__(self, path, limit="50"):
        self.path = Path(path)
        self.limit = money(limit)
        if not 0 < self.limit <= 50:
            raise BudgetError("This experiment is authorized for at most $50")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def edit(self):
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                try:
                    state = json.loads(self.path.read_text())
                except (ValueError, OSError):
                    raise BudgetError("Budget ledger is unreadable; refusing to reset it") from None
                if money(state["limit_usd"]) != self.limit or not isinstance(state["requests"], dict):
                    raise BudgetError("Ledger settings differ; do not create a replacement ledger")
            else:
                state = {"schema": 1, "limit_usd": str(self.limit), "requests": {}}
            yield state
            temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
            with temporary.open("w") as output:
                json.dump(state, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)

    def reserve(self, run_id, ceiling, run_limit):
        ceiling, run_limit = money(ceiling), money(run_limit)
        if not 0 < run_limit <= self.limit:
            raise BudgetError("Invalid per-run spending limit")
        with self.edit() as state:
            rows = list(state["requests"].values())
            spent = sum((accounted(r) for r in rows), Decimal(0))
            run_spent = sum((accounted(r) for r in rows if r["run_id"] == run_id), Decimal(0))
            if spent + ceiling > self.limit or run_spent + ceiling > run_limit:
                raise BudgetError("The next request could exceed the experiment or run budget")
            request_id = uuid.uuid4().hex
            state["requests"][request_id] = {"run_id": run_id, "reserved_usd": str(ceiling),
                "status": "pending", "cost_usd": None, "generation_id": None}
        return request_id

    def hold(self, request_id, evidence):
        """Keep the entire reservation counted when the actual charge is unknown."""
        if not evidence:
            raise BudgetError("Record inspected evidence before holding an unknown charge")
        with self.edit() as state:
            row = state["requests"][request_id]
            if row["status"] not in {"pending", "reconciliation_required", "billing_hold"}:
                raise BudgetError("Cannot replace confirmed billing with a hold")
            if row.get("cost_usd") is not None:
                raise BudgetError("A known cost requires billing reconciliation")
            row.update(status="billing_hold", recovery=evidence)

    def settle(self, request_id, cost, generation_id):
        cost = money(cost)
        exceeded = False
        with self.edit() as state:
            request = state["requests"][request_id]
            if request["status"] == "settled":
                raise BudgetError("Request is already settled")
            exceeded = cost > money(request["reserved_usd"])
            request.update(status="settled" if not exceeded else "cost_exceeded_reservation",
                           cost_usd=str(cost), generation_id=generation_id)
        if exceeded:
            raise BudgetError("Reported cost exceeded the reservation. Stop and inspect provider billing.")

    def unresolved(self, request_id, reason, generation_id=None):
        with self.edit() as state:
            row = state["requests"][request_id]
            if row["status"] != "settled":
                row.update(status="reconciliation_required", reason=reason, generation_id=generation_id)


def main():
    import argparse
    from datetime import datetime, timezone
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--request-id", required=True)
    reconcile.add_argument("--actual-cost", required=True)
    reconcile.add_argument("--generation-id", required=True)
    reconcile.add_argument("--evidence-note", required=True,
                           help="Describe the checked OpenRouter activity record; never include credentials")
    a = p.parse_args()
    path = Path(a.ledger)
    if a.command == "status":
        print(path.read_text() if path.exists() else "No spending ledger exists yet.")
        return
    if not path.exists():
        p.error("Cannot reconcile a missing ledger")
    state = json.loads(path.read_text())
    ledger = Ledger(path, state["limit_usd"])
    ledger.settle(a.request_id, a.actual_cost, a.generation_id)
    with ledger.edit() as state:
        state["requests"][a.request_id]["reconciliation"] = {
            "evidence_note": a.evidence_note, "timestamp": datetime.now(timezone.utc).isoformat()}
    print("Recorded the verified cost. Preserve this ledger for all subsequent runs.")


if __name__ == "__main__":
    main()
