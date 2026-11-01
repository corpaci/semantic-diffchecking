"""Non-executing decoder for a deliberately restricted Python equation fragment."""
import ast
import hashlib
import json
from pathlib import Path


class UnsupportedCode(ValueError):
    pass


def decode(source):
    if len(source.encode()) > 65536:
        raise UnsupportedCode("Source exceeds 64 KiB")
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError) as error:
        raise UnsupportedCode(type(error).__name__) from None
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body.pop(0)
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
        raise UnsupportedCode("One function only; no imports or module execution")
    fn = body[0]
    args = fn.args
    if (fn.name != "law" or fn.decorator_list or args.posonlyargs or args.kwonlyargs or args.defaults
            or args.kw_defaults or args.vararg or args.kwarg or
            [a.arg for a in args.args] != ["op", "x", "y", "z"]):
        raise UnsupportedCode("Expected law(op, x, y, z), without defaults or decorators")
    # Reject annotations too: they can execute when a function is defined.
    if fn.returns or any(a.annotation for a in args.args):
        raise UnsupportedCode("Annotations are outside the grammar")
    env = {v: v for v in ("x", "y", "z")}
    operations = 0

    def term(node):
        nonlocal operations
        operations += 1
        if operations > 256:
            raise UnsupportedCode("Expanded term exceeds parser bound")
        if isinstance(node, ast.Name) and node.id in env:
            return env[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "op"
                and len(node.args) == 2 and not node.keywords):
            result = f"({term(node.args[0])} * {term(node.args[1])})"
            if len(result) > 4096:
                raise UnsupportedCode("Expanded expression too large")
            return result
        raise UnsupportedCode("Terms must be arguments, local term aliases, or binary op calls")

    statements = list(fn.body)
    if statements and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant) and isinstance(statements[0].value.value, str):
        statements.pop(0)
    if not statements or not isinstance(statements[-1], ast.Return):
        raise UnsupportedCode("Expected a final return")
    for statement in statements[:-1]:
        if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)):
            raise UnsupportedCode("Only straight-line local assignments are supported")
        name = statement.targets[0].id
        if name in {"op", "x", "y", "z"} or name in env:
            raise UnsupportedCode("No argument rebinding or local reassignment")
        env[name] = term(statement.value)
    result = statements[-1].value
    if not (isinstance(result, ast.Compare) and len(result.ops) == 1 and isinstance(result.ops[0], ast.Eq)):
        raise UnsupportedCode("Return exactly one equality between terms")
    return f"{term(result.left)} = {term(result.comparators[0])}"


class Oracle:
    """Use existing mapper without altering its module globals or data paths."""
    def __init__(self, source, data):
        import sys
        source, data = Path(source).resolve(), Path(data).resolve()
        sys.path.insert(0, str(source))
        from mapper import NodeMapper
        from oracle import SemanticOracle
        import mmap
        self.oracle = SemanticOracle.__new__(SemanticOracle)
        self.oracle.meta = json.loads((data / "matrix_meta.json").read_text())
        self.oracle.n = self.oracle.meta["n"]
        if (data / "matrix.bin").stat().st_size != self.oracle.n ** 2:
            raise ValueError("Oracle matrix size mismatch")
        self.file = (data / "matrix.bin").open("rb")
        self.oracle.matrix = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.oracle.mapper = NodeMapper(str(data / "equations.txt"))

    def compare(self, original, candidate):
        from dataclasses import asdict
        return asdict(self.oracle.compare(original, candidate))

    def close(self):
        self.oracle.matrix.close()
        self.file.close()


def pointwise_probe(original_eq, generated_eq):
    """Exhaust all 16 binary operation tables on {0,1} and all 8 assignments.

    No candidate code executes. These probes can refute pointwise equivalence;
    passing does not prove it and is separate from universal-law equivalence.
    """
    from itertools import product
    from normalizer import parse_equation, Var
    original, candidate = parse_equation(original_eq), parse_equation(generated_eq)

    def value(term, env, table):
        if isinstance(term, Var):
            return env[term.name]
        return table[2 * value(term.left, env, table) + value(term.right, env, table)]

    for table in product(range(2), repeat=4):
        for assignment in product(range(2), repeat=3):
            env = dict(zip(("x", "y", "z"), assignment))
            before = value(original.lhs, env, table) == value(original.rhs, env, table)
            after = value(candidate.lhs, env, table) == value(candidate.rhs, env, table)
            if before != after:
                return dict(status="counterexample", table=list(table), assignment=env,
                            original=before, generated=after)
    return dict(status="passed_finite_probes", probes=128, proof=False)
