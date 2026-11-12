"""Offline checks for intervention isolation and prompt-delivery evidence."""
import copy
import unittest

from .contract import NONE, EVERY_CALL, PLANNING_ONLY, apply_contract, contract_message, delivery_audit, inject_for_role


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.requirement = "Keep balance public. Allow zero.\nReturn the balance."
        self.messages = [{"role": "system", "content": "Native role and JSON format instructions."},
                         {"role": "user", "content": "Review this generated design."}]

    def test_baseline_prompt_is_unchanged(self):
        self.assertIs(apply_contract(self.messages), self.messages)

    def test_injection_preserves_native_messages_and_exact_original(self):
        before = copy.deepcopy(self.messages)
        result = apply_contract(self.messages, self.requirement)
        self.assertEqual(self.messages, before)
        self.assertEqual(result, [before[0], contract_message(self.requirement), before[1]])
        self.assertIn(self.requirement, result[1]["content"])

    def test_duplicate_injection_is_rejected(self):
        result = apply_contract(self.messages, self.requirement)
        with self.assertRaisesRegex(ValueError, "already applied"):
            apply_contract(result, self.requirement)

    def test_delivery_requires_exact_contract_in_actual_http_payload(self):
        messages = apply_contract(self.messages, self.requirement)
        events = [{"kind": "llm_request", "messages": messages},
                  {"kind": "openrouter_request", "payload": {"messages": messages}}]
        self.assertEqual(delivery_audit(events, self.requirement, EVERY_CALL)["verified_calls"], 1)
        with self.assertRaisesRegex(ValueError, "planned condition"):
            delivery_audit(events, self.requirement, NONE)
        with self.assertRaisesRegex(ValueError, "planned condition"):
            delivery_audit(events, self.requirement + " Changed.", EVERY_CALL)
        events[1] = {"kind": "openrouter_request", "payload": {"messages": self.messages}}
        with self.assertRaisesRegex(ValueError, "payload differ"):
            delivery_audit(events, self.requirement, EVERY_CALL)

    def test_missing_http_request_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            delivery_audit([{"kind": "llm_request", "messages": self.messages}], self.requirement, NONE)

    def test_planning_only_excludes_coding_and_all_review_calls(self):
        events = []
        roles = ["Product Manager", "Architect", "Project Manager", "Engineer", "Engineer", "Engineer"]
        for role in roles:
            selected = inject_for_role(PLANNING_ONLY, role)
            self.assertEqual(selected, role in {"Architect", "Project Manager"})
            messages = apply_contract(self.messages, self.requirement if selected else None)
            events.extend([{"kind": "llm_request", "role": role, "messages": messages},
                           {"kind": "openrouter_request", "payload": {"messages": messages}}])
        audit = delivery_audit(events, self.requirement, PLANNING_ONLY)
        self.assertEqual(audit["injected_calls"], 2)
        self.assertEqual(audit["injected_roles"], ["Architect", "Project Manager"])
        # A direct injection into an Engineer call invalidates the arm.
        leaked = apply_contract(self.messages, self.requirement)
        events[-2]["messages"] = leaked
        events[-1]["payload"]["messages"] = leaked
        with self.assertRaisesRegex(ValueError, "planned condition"):
            delivery_audit(events, self.requirement, PLANNING_ONLY)

    def test_planning_only_rejects_unknown_or_missing_stages(self):
        with self.assertRaisesRegex(ValueError, "recognized native role"):
            inject_for_role(PLANNING_ONLY, "unknown")
        messages = apply_contract(self.messages, self.requirement)
        events = [{"kind": "llm_request", "role": "Architect", "messages": messages},
                  {"kind": "openrouter_request", "payload": {"messages": messages}}]
        with self.assertRaisesRegex(ValueError, "Both selected planning stages"):
            delivery_audit(events, self.requirement, PLANNING_ONLY)


if __name__ == "__main__":
    unittest.main()
