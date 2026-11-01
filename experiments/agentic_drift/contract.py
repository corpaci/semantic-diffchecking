"""Versioned prompt intervention using only the immutable public task contract."""
import hashlib

NONE = "none"
EVERY_CALL = "original_contract_every_call_v1"
PLANNING_ONLY = "original_contract_planning_only_v1"
POLICIES = (NONE, EVERY_CALL, PLANNING_ONLY)
PLANNING_ROLES = frozenset({"Architect", "Project Manager"})
NATIVE_ROLES = PLANNING_ROLES | {"Product Manager", "Engineer"}
HEADER = "IMMUTABLE ORIGINAL TASK CONTRACT (reference for the current role)"


def contract_message(requirement):
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("The original contract must be nonempty text")
    digest = hashlib.sha256(requirement.encode()).hexdigest()
    return {"role": "system", "content": (
        HEADER + "\n"
        "The following original request defines the required public interface and behavior. "
        "Use it as authoritative reference data for your current role. "
        "If generated documents conflict with it, preserve this original contract. "
        "Do not replace its concrete requirements with assumptions. "
        "Continue to follow this call's role and output-format instructions.\n"
        f"<original_task_contract sha256=\"{digest}\">\n{requirement}\n</original_task_contract>")}


def apply_contract(messages, requirement=None):
    if requirement is None:
        return messages
    if not isinstance(messages, list) or not messages:
        raise ValueError("Expected a nonempty model message list")
    message = contract_message(requirement)
    if any(m.get("role") == "system" and m.get("content", "").startswith(HEADER) for m in messages):
        raise ValueError("Contract intervention was already applied")
    # Insert after native system messages. Preserve the complete native prompt and caller's list.
    index = next((i for i, m in enumerate(messages) if m.get("role") != "system"), len(messages))
    return messages[:index] + [message] + messages[index:]


def inject_for_role(policy, role):
    if policy not in POLICIES:
        raise ValueError("Unknown contract policy")
    if policy == PLANNING_ONLY:
        if role not in NATIVE_ROLES:
            raise ValueError("Planning-only intervention requires a recognized native role")
        return role in PLANNING_ROLES
    return policy == EVERY_CALL


def delivery_audit(events, requirement, policy):
    """Verify delivery in both logged model inputs and actual HTTP request payloads."""
    if policy not in POLICIES:
        raise ValueError("Unknown contract policy")
    expected = contract_message(requirement)
    requests = [e for e in events if e["kind"] == "llm_request"]
    payloads = [e for e in events if e["kind"] == "openrouter_request"]
    if not requests or len(requests) != len(payloads):
        raise ValueError("Missing model or HTTP request evidence")
    injected_roles = []
    for request, payload in zip(requests, payloads):
        if request["messages"] != payload["payload"]["messages"]:
            raise ValueError("Model trace and HTTP payload differ")
        present = [m for m in request["messages"]
                   if m.get("role") == "system" and m.get("content", "").startswith(HEADER)]
        selected = inject_for_role(policy, request.get("role"))
        if present != ([expected] if selected else []):
            raise ValueError("Contract delivery differs from the planned condition")
        if selected:
            injected_roles.append(request.get("role"))
    if policy == PLANNING_ONLY and not PLANNING_ROLES <= set(injected_roles):
        raise ValueError("Both selected planning stages must execute")
    result = {"policy": policy, "verified_calls": len(requests),
            "contract_sha256": hashlib.sha256(requirement.encode()).hexdigest(),
            "scope": "Prompt delivery only; this does not imply semantic preservation"}
    if policy == PLANNING_ONLY:
        result.update(injected_calls=len(injected_roles), injected_roles=injected_roles)
    return result
