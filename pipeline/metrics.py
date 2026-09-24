"""Metrics on oracle-labeled rows, with explicit denominators."""

from collections import defaultdict

LABELS = ("equivalent", "weaker", "stronger", "incomparable")


def summarize(rows, metrics):
    """Summarize scored JSONL rows. Undefined rates are None, not zero."""
    rows = list(rows)
    for row in rows:
        if row.get("label") not in LABELS or row.get("pred") not in LABELS:
            raise ValueError("evaluation requires resolved gold and predicted relation labels")
    n = len(rows)
    result = {"n": n}
    if "accuracy" in metrics:
        result["accuracy"] = sum(r["label"] == r["pred"] for r in rows) / n if n else None
    for name, equivalent in (("false_equivalence", False), ("missed_equivalence", True)):
        if name in metrics:
            eligible = [r for r in rows if (r["label"] == "equivalent") == equivalent]
            errors = sum((r["pred"] == "equivalent") != equivalent for r in eligible)
            result[name] = {"errors": errors, "eligible": len(eligible),
                            "rate": errors / len(eligible) if eligible else None}
    if "per_label" in metrics:
        result["per_label"] = {}
        for label in LABELS:
            support = sum(r["label"] == label for r in rows)
            predicted = sum(r["pred"] == label for r in rows)
            correct = sum(r["label"] == r["pred"] == label for r in rows)
            result["per_label"][label] = {
                "support": support, "predicted": predicted,
                "recall": correct / support if support else None,
                "precision": correct / predicted if predicted else None,
            }
    if "per_tier" in metrics:
        tiers = defaultdict(list)
        for row in rows:
            tiers[row.get("tier", "unspecified")].append(row)
        result["per_tier"] = {
            tier: summarize(group, ["accuracy", "false_equivalence", "missed_equivalence"])
            for tier, group in sorted(tiers.items())
        }
    return result
