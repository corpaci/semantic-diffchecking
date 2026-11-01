"""Authored, bounded fixtures. Expected outcomes are private evaluation data."""
import itertools


def ordinary_tasks():
    tasks = {}

    def add(name, signature, requirements, reference, rows, mutations):
        tasks[name] = dict(id=name, track="ordinary", signature=signature,
                          requirements={f"R{i:02}": s for i, s in enumerate(requirements, 1)},
                          reference=reference, rows=rows, mutations=mutations)

    def row(args, expected, req, kind="value", raises=None):
        return dict(args=list(args), expected=expected, requirements=req, kind=kind, raises=raises)

    permissions = '''def permitted(role, action, owner, locked):
    if role not in ("admin", "editor", "viewer") or action not in ("read", "write", "delete"):
        return False
    if action == "read":
        return True
    if locked:
        return False
    return role == "admin" or (role == "editor" and action == "write" and owner)
'''
    rows = []
    for role, action, owner, locked in itertools.product(
            ["admin", "editor", "viewer", "guest", "ADMIN"],
            ["read", "write", "delete", "share", "READ"], [False, True], [False, True]):
        known = role in {"admin", "editor", "viewer"} and action in {"read", "write", "delete"}
        allowed = known and (action == "read" or (not locked and
                    (role == "admin" or (role == "editor" and owner and action == "write"))))
        req = ["R01" if not known else "R02" if action == "read" else
               "R03" if locked else "R04" if role == "admin" else "R05" if role == "editor" else "R06"]
        rows.append(row((role, action, owner, locked), allowed, req, "admission"))
    add("permissions", "permitted(role, action, owner, locked)", [
        "Unknown roles or actions return False. Matching is case-sensitive.",
        "Admin, editor, and viewer may read, even when locked.",
        "Locked resources reject all writes and deletes, including admin requests.",
        "On unlocked resources, admin may write and delete regardless of ownership.",
        "On unlocked resources, editor may write only when owner is True; editor cannot delete.",
        "Viewer cannot write or delete. Inputs owner and locked are booleans; return a bool."
    ], permissions, rows, [permissions.replace("if locked:", "if locked and role != \"admin\":"),
                           permissions.replace('if action == "read":', 'if action == "read" and not locked:')])

    transitions = {("draft", "submit"): "pending", ("pending", "approve"): "approved",
                   ("pending", "reject"): "draft", ("approved", "cancel"): "cancelled"}
    state_ref = '''def transition(state, event):
    changes = {("draft", "submit"): "pending", ("pending", "approve"): "approved",
               ("pending", "reject"): "draft", ("approved", "cancel"): "cancelled"}
    if (state, event) not in changes:
        raise ValueError("Invalid transition")
    return changes[state, event]
'''
    rows = []
    for state, event in itertools.product(["draft", "pending", "approved", "cancelled", "unknown"],
                                           ["submit", "approve", "reject", "cancel", "unknown"]):
        pair = (state, event)
        req = [f"R{list(transitions).index(pair)+1:02}"] if pair in transitions else ["R05"]
        rows.append(row(pair, transitions.get(pair), req, "transition",
                        None if pair in transitions else ["ValueError", "Invalid transition"]))
    add("state_machine", "transition(state, event)", [
        "draft plus submit returns pending.", "pending plus approve returns approved.",
        "pending plus reject returns draft.", "approved plus cancel returns cancelled.",
        "All other pairs raise ValueError('Invalid transition'); cancelled is terminal. Inputs are strings."
    ], state_ref, rows, [state_ref.replace('raise ValueError("Invalid transition")', 'return state'),
                        state_ref.replace('"cancelled"}', '"draft"}')])

    booking_ref = '''def can_book(existing, start, end, capacity):
    if start >= end:
        return False
    points = sorted({start, end} | {p for interval in existing for p in interval if start < p < end})
    for point in points[:-1]:
        if 1 + sum(a <= point < b for a, b in existing) > capacity:
            return False
    return True
'''
    intervals = [(a, b) for a in range(4) for b in range(a + 1, 4)]
    histories = [[]] + [[p] for p in intervals] + [list(p) for p in itertools.product(intervals, repeat=2)]
    rows = []
    for existing, start, end, capacity in itertools.product(histories, range(4), range(4), [1, 2]):
        # Integer endpoints make each unit slot a complete bounded occupancy oracle.
        allowed = start < end and all(
            1 + sum(a <= t < b for a, b in existing) <= capacity for t in range(start, end))
        rows.append(row((existing, start, end, capacity), allowed,
                        ["R01"] if start >= end else ["R03"], "admission"))
    for existing, start, end, capacity, allowed in [([(0, 1)], 1, 2, 1, True),
            ([(1, 2)], 0, 1, 1, True), ([(0, 2)], 1, 2, 1, False)]:
        rows.append(row((existing, start, end, capacity), allowed, ["R02"], "admission"))
    add("bookings", "can_book(existing, start, end, capacity)", [
        "A proposed interval with start >= end returns False.",
        "Intervals are half-open [start,end); touching endpoints do not overlap.",
        "Return True exactly when adding the proposal never exceeds capacity at any time; equality is allowed.",
        "Do not mutate existing, including on rejection. Return a bool. Inputs are integer endpoints, positive integer capacity, and valid existing intervals."
    ], booking_ref, rows, [booking_ref.replace('> capacity:', '>= capacity:'),
                          booking_ref.replace('a <= point < b', 'a <= point <= b')])

    username_ref = '''def valid_username(value):
    if not isinstance(value, str) or not 3 <= len(value) <= 12:
        return False
    if not ("a" <= value[0] <= "z" or "A" <= value[0] <= "Z"):
        return False
    if any(not ("a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9" or c == "_") for c in value):
        return False
    return value.lower() not in {"admin", "root", "system"}
'''
    values = [None, 7, True, [], {}, "abc", "a"*12, "a"*13, "Admin", "ROOT", "System", "admin_",
              "éab", "aéb", "a b", "a\nb", "a-b", "a.b", "Ａbc", "a１b"]
    values += ["".join(p) for n in range(5) for p in itertools.product("a1_!", repeat=n)]
    rows = []
    for v in values:
        req = "R01" if not isinstance(v, str) else "R02" if not 3 <= len(v) <= 12 else "R03" if v[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" else "R04" if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in v) else "R05"
        expected = isinstance(v, str) and 3 <= len(v) <= 12 and v[0] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" and set(v) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_") and v.lower() not in {"admin", "root", "system"}
        rows.append(row((v,), bool(expected), [req], "admission"))
    add("input_validation", "valid_username(value)", [
        "Non-string inputs return False without raising.", "Length must be between 3 and 12 inclusive.",
        "The first character must be an ASCII letter.",
        "Every character must be an ASCII letter, ASCII digit, or underscore; whitespace is forbidden.",
        "Reject admin, root, and system regardless of case. Otherwise accept. Return a bool."
    ], username_ref, rows, [username_ref.replace('value.lower() not in', 'value not in'),
                          username_ref.replace('3 <= len(value)', '3 < len(value)')])
    return tasks


def etp_tasks():
    laws = {
        "etp_projection": "op(x, y) == x",
        "etp_associativity": "op(op(x, y), z) == op(x, op(y, z))",
        "etp_absorption": "op(x, op(x, y)) == x",
        "etp_reassociation": "op(op(x, y), y) == op(x, op(y, y))",
    }
    return {name: dict(id=name, track="etp", signature="law(op, x, y, z)",
                      reference=f"def law(op, x, y, z):\n    return {law}\n",
                      requirements={"R01": "Preserve the universally quantified magma identity encoded by the original code.",
                                    "R02": "Preserve the Boolean result for each argument assignment, with a pure total arbitrary binary op.",
                                    "R03": "Stay within the documented straight-line equation code grammar and fixed interface."})
            for name, law in laws.items()}


def all_tasks():
    return ordinary_tasks() | etp_tasks()
