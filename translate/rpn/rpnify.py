"""ETP formal equation -> reverse Polish (postfix), optionally as a stack program.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    tokens   x y z ◇ ◇ x y ◇ z ◇ =
    program  PUSH x; PUSH y; PUSH z; OP; OP; PUSH x; PUSH y; OP; PUSH z; OP; EQ

No delimiters and no arity words: the structure is recoverable only by
simulating a stack. That makes the failure mode legible — a reader that pops in
the wrong order produces a specific, nameable wrong tree rather than noise,
which is worth more than a rendering that fails opaquely.

Both forms carry identical information; `--form program` just spells the stack
machine out. The reader accepts either, distinguished by the `;` separators
that the token form never contains.

CLI:  python3 rpnify.py 4512 --form program | python3 rpnify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main,
)

FORMS = ("tokens", "program")


def _postfix(term) -> str:
    if isinstance(term, Var):
        return term.name
    return f"{_postfix(term.left)} {_postfix(term.right)} {CANONICAL_OP}"


def render_tokens(equation: Equation) -> str:
    """Postfix token sequence, ending in `=`."""
    return f"{_postfix(equation.lhs)} {_postfix(equation.rhs)} ="


def render_program(equation: Equation) -> str:
    """The same sequence spelled out as stack-machine steps."""
    steps = []
    for token in render_tokens(equation).split():
        steps.append("OP" if token == CANONICAL_OP else "EQ" if token == "=" else f"PUSH {token}")
    return "; ".join(steps)


def _tokens(text: str) -> list[str]:
    """Normalize either form to a token list."""
    text = text.strip()
    if ";" not in text:
        return text.split()
    out = []
    for raw in text.split(";"):
        step = raw.strip()
        if not step:
            continue
        if step == "OP":
            out.append(CANONICAL_OP)
        elif step == "EQ":
            out.append("=")
        elif step.startswith("PUSH "):
            out.append(step[len("PUSH "):].strip())
        else:
            raise ParseFailure(f"unknown step {step!r}")
    return out


def read_back(text: str) -> Equation:
    """Run the stack machine, then hand the result to the oracle's parser."""
    tokens = _tokens(text)
    if tokens.count("=") != 1 or tokens[-1] != "=":
        raise ParseFailure("the sequence must end with exactly one '='")
    stack: list[str] = []
    for token in tokens:
        if token in (CANONICAL_OP, "="):
            if len(stack) < 2:
                raise ParseFailure(f"stack underflow at {token!r}")
            right, left = stack.pop(), stack.pop()
            stack.append(f"{left} = {right}" if token == "="
                         else f"({left} {CANONICAL_OP} {right})")
        else:
            if not token.isalnum():
                raise ParseFailure(f"not a variable: {token!r}")
            stack.append(token)
    if len(stack) != 1:
        raise ParseFailure(f"{len(stack)} items left on the stack, expected 1")
    return parse_equation(stack[0])


def add_style_args(parser) -> None:
    """Register `--form`."""
    parser.add_argument("--form", choices=FORMS, default="tokens",
                        help="postfix tokens (default) or spelled-out stack steps")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    form = getattr(args, "form", "tokens")
    return Representation(
        name="rpn", key="rpn",
        render=render_program if form == "program" else render_tokens,
        read_back=read_back, blurb="reverse Polish (postfix) notation",
        style={"form": form, "operator": CANONICAL_OP, "terminator": "="},
    )


_CASES = (
    ("x = x", "x x ="),
    ("x ◇ y = y ◇ x", "x y ◇ y x ◇ ="),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z", "x y z ◇ ◇ x y ◇ z ◇ ="),
)

_BAD = (
    ("x y ◇ ◇ =", "stack underflow"),
    ("x y z =", "items left on the stack"),
    ("x y ◇ y x ◇", "no '=' at the end"),
    ("x y ◇ = y x ◇ =", "two '=' tokens"),
    ("PUSH x; POP; EQ", "an unknown stack step"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD, add_style_args)
