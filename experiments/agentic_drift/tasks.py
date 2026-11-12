"""Small authored calibration tasks, not a research benchmark."""
TASKS = {
    "stable_unique": {
        "requirement": "Implement stable_unique(items) in solution.py. Accept a list of integers. "
                       "Return each distinct integer once, in first-occurrence order. "
                       "Do not mutate the input. An empty input returns an empty list.",
        "obligations": ["unique", "first_occurrence_order", "input_unchanged", "empty_input"],
        "reference": "def stable_unique(items):\n    return list(dict.fromkeys(items))\n",
        "mutation": "def stable_unique(items):\n    return sorted(set(items))\n",
        "lost": "first_occurrence_order",
    },
    "bounded_sum": {
        "requirement": "Implement bounded_sum(items, lower, upper) in solution.py. "
                       "Sum integers x satisfying lower <= x < upper. Do not mutate items. "
                       "Return zero for an empty input. Assume lower <= upper.",
        "obligations": ["lower_inclusive", "upper_exclusive", "input_unchanged", "empty_input"],
        "reference": "def bounded_sum(items, lower, upper):\n    return sum(x for x in items if lower <= x < upper)\n",
        "mutation": "def bounded_sum(items, lower, upper):\n    return sum(x for x in items if lower <= x <= upper)\n",
        "lost": "upper_exclusive",
    },
    "first_index": {
        "requirement": "Implement first_index(items, target) in solution.py. Return the zero-based "
                       "index of the first occurrence of target. Return -1 when absent. "
                       "Do not mutate items. An empty list returns -1.",
        "obligations": ["first_match", "absent_minus_one", "input_unchanged", "empty_input"],
        "reference": "def first_index(items, target):\n    return next((i for i, x in enumerate(items) if x == target), -1)\n",
        "mutation": "def first_index(items, target):\n    return next((i for i in range(len(items)-1, -1, -1) if items[i] == target), -1)\n",
        "lost": "first_match",
    },
}


def public_task(task_id):
    task = TASKS[task_id]
    return {"task_id": task_id, "source": "authored_calibration_v1",
            "requirement": task["requirement"]}
