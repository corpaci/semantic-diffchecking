"""Explicit recovery of a response-less transport failure; never an automatic retry."""
import json
from datetime import datetime, timezone

from ..budget import Ledger, accounted
from ..trace import dump


def recover(out, plan, chain_id, request_id, execute=False):
    from .study import digest

    if chain_id not in {row["id"] for row in plan["rows"]}:
        raise ValueError("Chain is not in the frozen schedule")
    chain = out / "chains" / chain_id
    status_path = chain / "status.json"
    status = json.loads(status_path.read_text())
    hop = status.get("attempted_hop")
    if status.get("status") != "request_stopped" or hop != status["completed_hops"] + 1:
        raise ValueError("Inspect the stopped request before recovering it")
    expected = {f"hop-{h:03}.py" for h in range(hop)}
    if set(status.get("artifact_hashes", {})) != expected:
        raise ValueError("Saved checkpoint manifest is incomplete")
    for name, value in status["artifact_hashes"].items():
        if digest(chain / name) != value:
            raise ValueError("Saved checkpoint changed: " + name)
    if any((chain / name).exists() for name in (f"hop-{hop:03}.py", f"hop-{hop:03}-response.txt")):
        raise ValueError("A saved artifact exists; inspect it instead of retrying")
    events_path = chain / "transport/events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    requests = [event for event in events if event["kind"] == "openrouter_request"]
    related = [event for event in events if event.get("reservation_id") == request_id]
    allowed = {"RemoteProtocolError", "ReadError", "WriteError", "ConnectError", "timeout_ambiguous_billing"}
    if (not requests or requests[-1]["reservation_id"] != request_id
            or [event["kind"] for event in related] != ["openrouter_request", "openrouter_error"]
            or related[-1].get("category") not in allowed or related[-1].get("generation_id") is not None):
        raise ValueError("Only the latest response-less transport failure can be recovered")
    row = next(row for row in plan["rows"] if row["id"] == chain_id)
    payload = related[0]["payload"]
    config = plan["configs"][row["family"]]
    if (payload["model"] != config["model"] or payload["max_tokens"] != config["max_tokens"]
            or payload["messages"] != json.loads((chain / f"hop-{hop:03}-input.json").read_text())):
        raise ValueError("Interrupted request differs from its frozen inputs")
    ledger = Ledger(plan["ledger"], "50")
    state = json.loads(ledger.path.read_text())
    charge = state["requests"][request_id]
    if (charge["run_id"] != plan["study_id"] + ":" + chain_id
            or charge["status"] not in {"pending", "reconciliation_required", "billing_hold"}
            or charge.get("generation_id") is not None or charge.get("cost_usd") is not None
            or charge["reserved_usd"] != related[0]["reserved_usd"]):
        raise ValueError("Interrupted billing state changed")
    for key, value in state["requests"].items():
        if key != request_id:
            accounted(value)
    print(json.dumps(dict(status="recovery_checked", chain=chain_id, retry_hop=hop,
                          full_reservation_held=charge["reserved_usd"], paid_requests_sent=0)))
    if not execute:
        return
    folder = out / "recovery" / request_id
    folder.mkdir(parents=True, exist_ok=True)
    for path in (status_path, ledger.path, events_path):
        backup = folder / ("original-" + path.name)
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    record = dict(timestamp=datetime.now(timezone.utc).isoformat(), chain=chain_id, retry_hop=hop,
                  request_id=request_id, actual_cost_verified=False, events_sha256=digest(events_path),
                  action="explicit retry from saved predecessor with full unknown-charge reservation")
    dump(folder / "recovery.json", record)
    ledger.hold(request_id, record)
    status.update(status="between_hops", recovery_request_id=request_id)
    dump(status_path, status)


def settled_truncation(trace, ledger, config, run_id):
    """Confirm the original raw response and its settled charge before skipping a chain."""
    try:
        events = [json.loads(line) for line in (trace.root / "events.jsonl").read_text().splitlines()]
        request = next(event for event in reversed(events) if event["kind"] == "openrouter_request")
        responses = [event for event in events if event["kind"] == "openrouter_raw_response"
                     and event.get("reservation_id") == request["reservation_id"]]
        if len(responses) != 1:
            return False
        response = responses[0]
        body = response.get("body", {})
        choices = body.get("choices", []) if isinstance(body, dict) else []
        charge = json.loads(ledger.path.read_text())["requests"][request["reservation_id"]]
        return (response["http_status"] == 200 and body.get("model") == config["model"]
                and request["payload"]["max_tokens"] == config["max_tokens"]
                and len(choices) == 1 and choices[0].get("finish_reason") == "length"
                and charge["status"] == "settled" and charge["run_id"] == run_id
                and bool(body.get("id")) and charge.get("generation_id") == body["id"]
                and accounted(charge) == accounted(dict(status="settled", cost_usd=body["usage"]["cost"])))
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration):
        return False
