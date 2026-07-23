"""Parse and normalize magma equations.

A magma equation is a single universally-quantified identity  s = t  over one
binary operation and variables. Nothing else — no constants, no second
operation, no chained equalities, no unparenthesized chains (the magma op is
not associative, so `a * b * c` is ambiguous and rejected).

Normalization collapses meaning-preserving differences:
  - operation symbol        (*, ., ∘, ◇, f(_,_), ... -> ◇)
  - variable names          (renamed x,y,z,w,u,v by first appearance)
  - orientation of  s = t   (an identity is symmetric; the canonical key
                             takes the lexicographically smaller orientation)
  - whitespace / redundant outer parentheses / quantifier prefixes
It never reorders arguments and never re-associates: those change meaning.

Library entry points: `parse_equation`, `normalize`, `canonical_key`, and the
convenience `analyze` (parse + normalize + metadata as a plain dict). Also
runnable as a CLI to inspect how a generated equation is parsed and normalized:

    python3 normalizer.py "a * (b * c) = (a * b) * c"
    python3 normalizer.py --json "p * q = q * p"
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass

CANONICAL_OP = "◇"
CANONICAL_VARS = "xyzwuvtsrqpn"  # first-appearance renaming order

# Infix symbols an LLM plausibly uses for the single binary operation.
INFIX_OPS = set("◇⋄⬦◆∘○◦·⋅*∗×+-/&%@#!?^~")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ParseFailure(Exception):
    """The text could not be read as an equation at all.

    Raised for syntactic breakage: unbalanced parentheses, an unparenthesized
    (ambiguous) operator chain, stray characters, no `=`, etc. Distinct from
    OutsideFragment so callers can label a "syntactically valid but semantically
    unfaithful" output separately from a "parsing failure" — both are outcome
    categories the Week-1 dataset tracks.
    """
    pass

class OutsideFragment(Exception):
    """The text parses, but is not a single-operation magma identity.

    Raised when the input is well-formed yet steps outside the ETP fragment:
    constants/numbers, a relational or logical symbol, more than one distinct
    operation, a chained equality, or more variables than the catalogue
    supports. Semantically meaningful, just not something the implication graph
    can speak about — the oracle reports it as `outside-fragment`.
    """
    pass

# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

# The AST is a binary tree: leaves are `Var` (a variable occurrence) and
# internal nodes are `Op` (an application of the single magma operation).
# Both expose the same three-method interface — render / size / variables —
# so the parser and normalizer can recurse over a term without type checks.


@dataclass(frozen=True)
class Var:
    """A leaf of the term tree: one occurrence of a variable (e.g. `x`).

    Frozen (hence hashable and value-comparable) so that two terms built from
    equal variables compare equal — this is what makes canonical-key lookup
    work. `name` is the variable's identifier as written; normalization later
    rewrites it to a canonical letter.
    """

    name: str

    def render(self, top: bool = True) -> str:
        """Render this variable back to source text — just its name.

        `top` (whether this node is the root of a term) is accepted only to
        match `Op.render`'s signature, so callers can recurse uniformly; a
        bare variable never needs parentheses, so it is ignored here.
        """
        return self.name

    def size(self) -> int:
        """Number of operation symbols beneath this node — zero for a leaf.

        Summed over an equation, this is the ETP "order" used to decide
        whether a law is small enough to appear in the catalogue.
        """
        return 0

    def variables(self, acc: list) -> None:
        """Append this variable to `acc` in first-appearance order (no dups).

        `acc` is threaded through a left-to-right traversal, so the resulting
        list is exactly the canonical renaming order used by normalization.
        """
        if self.name not in acc:
            acc.append(self.name)

@dataclass(frozen=True)
class Op:
    """An internal node: the single binary magma operation applied to two
    subterms, `left ◇ right`.

    The tree shape *is* the meaning here — because the magma operation is
    neither associative nor commutative, `Op(a, Op(b, c))`, `Op(Op(a, b), c)`,
    and `Op(b, a)` are three genuinely different terms and are kept distinct.
    """

    left: "Var | Op"
    right: "Var | Op"

    def render(self, top: bool = True) -> str:
        """Render to canonical infix text, e.g. `x ◇ (y ◇ z)`.

        Always uses the canonical operator symbol. Parenthesizes itself unless
        it is the root of the term (`top=True`): the outermost operator needs
        no wrapping, but every nested operator does, which is what pins down
        the tree structure unambiguously on the way back to a string.
        """
        s = f"{self.left.render(False)} {CANONICAL_OP} {self.right.render(False)}"
        return s if top else f"({s})"

    def size(self) -> int:
        """Operation-symbol count of the whole subtree: this node plus both
        children — i.e. the term's contribution to the ETP order."""
        return 1 + self.left.size() + self.right.size()

    def variables(self, acc: list) -> None:
        """Collect variables in left-to-right first-appearance order by
        recursing into the left child before the right."""
        self.left.variables(acc)
        self.right.variables(acc)

@dataclass(frozen=True)
class Equation:
    """A full magma law: an identity `lhs = rhs` between two terms.

    Semantically the identity is symmetric (`s = t` and `t = s` are the same
    law), but this dataclass stores a fixed orientation as written; the
    orientation is quotiented away only when `canonical_key` is computed.
    """

    lhs: "Var | Op"
    rhs: "Var | Op"

    def render(self) -> str:
        """Render the whole equation, e.g. `x ◇ y = y ◇ x`. Each side is
        rendered as a root term (so no spurious outer parentheses)."""
        return f"{self.lhs.render()} = {self.rhs.render()}"

    def size(self) -> int:
        """The ETP order of the law: total operation symbols across both
        sides. Compared against MAX_ORDER to decide catalogue membership."""
        return self.lhs.size() + self.rhs.size()

# ---------------------------------------------------------------------------
# Cleanup of raw LLM output (before tokenizing)
# ---------------------------------------------------------------------------

_QUANTIFIER = re.compile(
    r"^\s*(?:∀|\\forall|for\s+all|for\s+every|for\s+any)\b[\w\s,]*?[,.:]\s*",
    re.IGNORECASE,
)

def strip_noise(text: str) -> str:
    """Strip the packaging an LLM tends to wrap a formula in, before tokenizing.

    Handles, in order: markdown code fences and stray backticks; `$...$` math
    delimiters; a handful of common LaTeX operator macros rewritten to their
    Unicode symbols; a leading universal-quantifier prefix (`∀ x y,` / `for all
    ...,`), which is implicit for every ETP law and carries no extra meaning;
    and a trailing sentence period. Returns the bare `s = t` core. This only
    removes semantically inert wrapping — it never touches the operator
    structure — so it cannot change which law is meant."""
    s = text.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    s = s.strip("`").strip()
    s = re.sub(r"^\$+\s*|\s*\$+$", "", s).strip()
    s = s.replace(r"\cdot", "·").replace(r"\circ", "∘").replace(r"\diamond", "◇")
    s = s.replace(r"\ast", "*").replace(r"\times", "×").replace(r"\left", "").replace(r"\right", "")
    while True:
        stripped = _QUANTIFIER.sub("", s)
        if stripped == s:
            break
        s = stripped.strip()
    s = s.rstrip(".").strip()
    return s

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:(?P<eq>==|=|≡)|(?P<lp>\()|(?P<rp>\))|(?P<comma>,)"
    r"|(?P<ident>[A-Za-z_][A-Za-z_0-9]*)|(?P<num>\d+)|(?P<sym>.))"
)

def tokenize(s: str):
    """Turn a cleaned equation string into a flat list of `(kind, value)`
    tokens for the parser.

    Kinds emitted: EQ, LP, RP, COMMA, IDENT (a variable or function name), and
    OP (a recognized infix operator symbol). The scanner is where the fragment
    boundary is first enforced: a numeric literal, or a relational/logical
    symbol such as `≠`, `→`, `∧`, is a well-formed token but *not* part of a
    plain single-operation identity, so it raises OutsideFragment; anything the
    scanner cannot classify at all raises ParseFailure.
    """
    tokens = []
    pos = 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise ParseFailure(f"cannot tokenize at position {pos}: {s[pos:pos+10]!r}")
        pos = m.end()
        if m.lastgroup == "eq":
            tokens.append(("EQ", m.group("eq")))
        elif m.lastgroup == "lp":
            tokens.append(("LP", "("))
        elif m.lastgroup == "rp":
            tokens.append(("RP", ")"))
        elif m.lastgroup == "comma":
            tokens.append(("COMMA", ","))
        elif m.lastgroup == "ident":
            tokens.append(("IDENT", m.group("ident")))
        elif m.lastgroup == "num":
            raise OutsideFragment(
                f"numeric constant {m.group('num')!r}: the fragment has variables only"
            )
        else:
            ch = m.group("sym")
            if ch in INFIX_OPS:
                tokens.append(("OP", ch))
            elif ch in "≠<>≤≥→⇒∧∨¬":
                raise OutsideFragment(f"symbol {ch!r} is not part of a plain identity")
            else:
                raise ParseFailure(f"unexpected character {ch!r}")
    return tokens

# ---------------------------------------------------------------------------
# Recursive-descent parser.  Grammar (single anonymous binary op):
#   equation := term EQ term
#   term     := atom [ OPSYM atom ]          (a second OPSYM => ambiguous chain)
#   atom     := IDENT | IDENT '(' term ',' term ')' | '(' term ')'
# ---------------------------------------------------------------------------

class _Parser:
    """A single-use recursive-descent parser over a token list.

    Builds an `Equation` AST while enforcing that the input is one identity
    over exactly one binary operation. It also records every distinct operator
    *spelling* it encounters (`op_symbols`): the ETP fragment has a single
    anonymous operation, so if the text mixes e.g. `*` and `+`, or `*` and a
    function-style `f(,)`, that is more than one operation and the law is
    outside the fragment. Not reusable — `i` is a mutable cursor into `tokens`.
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.op_symbols: set[str] = set()  # every distinct op spelling seen

    def peek(self):
        """Return the current token without consuming it, or a synthetic
        `("EOF", "")` sentinel once the stream is exhausted."""
        return self.tokens[self.i] if self.i < len(self.tokens) else ("EOF", "")

    def next(self):
        """Consume and return the current token (advancing the cursor)."""
        tok = self.peek()
        self.i += 1
        return tok

    def parse_equation(self) -> Equation:
        """Top of the grammar: `term '=' term`, then end of input.

        After parsing both sides it performs the whole-equation fragment
        checks that can only be made once everything is seen: a second `=`
        means a chained equality (not a single identity), leftover tokens are a
        parse error, and more than one distinct operator spelling means more
        than one operation. Returns the assembled `Equation`.
        """
        lhs = self.parse_term()
        kind, _ = self.next()
        if kind != "EQ":
            raise ParseFailure(f"expected '=' but found {kind}")
        rhs = self.parse_term()
        kind, val = self.peek()
        if kind == "EQ":
            raise OutsideFragment("chained equalities (a = b = c) are not a single identity")
        if kind != "EOF":
            raise ParseFailure(f"trailing input starting at {val!r}")
        if len(self.op_symbols) > 1:
            raise OutsideFragment(
                f"multiple distinct operation symbols {sorted(self.op_symbols)}: "
                "the fragment has exactly one binary operation"
            )
        return Equation(lhs, rhs)

    def parse_term(self):
        """Parse one `term := atom [ OP atom ]`.

        A term is a single atom, optionally followed by one infix operator and
        a second atom. Crucially it accepts *at most one* infix operator: a
        second one (`a * b * c`) is an unparenthesized chain, which is
        ambiguous under a non-associative operation and so is rejected as a
        ParseFailure rather than silently grouped.
        """
        left = self.parse_atom()
        kind, val = self.peek()
        if kind != "OP":
            return left
        self.next()
        self.op_symbols.add(val)
        right = self.parse_atom()
        kind, val = self.peek()
        if kind == "OP":
            raise ParseFailure(
                f"unparenthesized chain 'a {val} b {val} c': the operation is not "
                "associative, so grouping must be explicit"
            )
        return Op(left, right)

    def parse_atom(self):
        """Parse one `atom`: a variable, a function-style application, or a
        parenthesized subterm.

        Three shapes are accepted:
          - `IDENT` followed by `(` → a prefix operator `f(a, b)`, treated as
            the binary operation (its spelling `f(,)` is recorded so mixing it
            with an infix operator trips the single-operation check);
          - a bare `IDENT` → a `Var`;
          - `(` term `)` → the parenthesized term, which is how explicit
            grouping (and therefore tree shape) enters the AST.
        Anything else is a ParseFailure.
        """
        kind, val = self.next()
        if kind == "IDENT":
            if self.peek()[0] == "LP":  # function-style op(a, b)
                self.next()
                self.op_symbols.add(f"{val}(,)")
                a = self.parse_term()
                if self.next()[0] != "COMMA":
                    raise ParseFailure(f"expected ',' inside {val}(...)")
                b = self.parse_term()
                if self.next()[0] != "RP":
                    raise ParseFailure(f"expected ')' closing {val}(...)")
                return Op(a, b)
            return Var(val)
        if kind == "LP":
            t = self.parse_term()
            if self.next()[0] != "RP":
                raise ParseFailure("unbalanced parentheses")
            return t
        raise ParseFailure(f"expected a variable or '(' but found {kind} {val!r}")

def parse_equation(text: str) -> Equation:
    """Raw text → `Equation` AST.

    Pipeline: strip_noise → reject empty → tokenize → require at least one `=`
    → recursive-descent parse. This is what every other file calls to turn a
    string (an LLM output, or a catalogue line) into a structured term.

    Raises ParseFailure when the text cannot be read as an equation at all, or
    OutsideFragment when it reads fine but is not a single-binary-operation
    identity (multiple operators, constants, chained `=`, too many variables).
    Callers distinguish the two to label results appropriately.
    """
    cleaned = strip_noise(text)
    if not cleaned:
        raise ParseFailure("empty input")
    tokens = tokenize(cleaned)
    if not any(k == "EQ" for k, _ in tokens):
        raise ParseFailure("no '=' found: not an equation")
    return _Parser(tokens).parse_equation()

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _rename(term, mapping):
    """Return a copy of `term` with variables renamed to canonical letters.

    `mapping` accumulates original-name → canonical-letter assignments across
    the whole equation (so the same source variable maps consistently on both
    sides). New names are handed out in encounter order from CANONICAL_VARS;
    exhausting that pool means the law has more distinct variables than the
    fragment supports, hence OutsideFragment. Pure: builds fresh nodes rather
    than mutating the input (the AST is frozen anyway).
    """
    if isinstance(term, Var):
        if term.name not in mapping:
            if len(mapping) >= len(CANONICAL_VARS):
                raise OutsideFragment("too many distinct variables")
            mapping[term.name] = CANONICAL_VARS[len(mapping)]
        return Var(mapping[term.name])
    return Op(_rename(term.left, mapping), _rename(term.right, mapping))

def normalize(eq: Equation) -> Equation:
    """Alpha-normalize: rename variables to canonical letters by first
    appearance, scanning the LHS then the RHS.

    This collapses the meaning-preserving choice of variable names (so
    `a ◇ b = b ◇ a` and `p ◇ q = q ◇ p` become identical) while leaving tree
    shape and argument order — which carry meaning — untouched. Note it does
    *not* canonicalize the `=` orientation; that is `canonical_key`'s job.
    """
    mapping: dict = {}
    return Equation(_rename(eq.lhs, mapping), _rename(eq.rhs, mapping))

def canonical_key(eq: Equation) -> str:
    """The lookup key that identifies a law regardless of how it was written.

    Because an identity is symmetric, both `s = t` and `t = s` denote the same
    law; this normalizes each orientation independently and returns the
    lexicographically smaller rendering, so the two orientations — and any
    variable renaming of them — collapse to one string. Two equations share a
    canonical key iff they are the same ETP law, which is exactly the property
    the node mapper relies on for O(1) catalogue lookup.
    """
    a = normalize(eq).render()
    b = normalize(Equation(eq.rhs, eq.lhs)).render()
    return min(a, b)


# ---------------------------------------------------------------------------
# Convenience API + CLI
# ---------------------------------------------------------------------------


def analyze(text: str) -> dict:
    """Parse and normalize one equation string into a JSON-ready dict.

    This is the single function behind both the CLI and Python callers who just
    want "what did this parse to, and what is its normal form". It never raises
    for ordinary bad input — parse/normalize errors are returned as data.

    On success (`ok=True`):
      parsed         the equation rebuilt from the AST — structure recovered and
                     operator canonicalized to ◇, but the *original* variable
                     names kept, so you can see how the text was grouped;
      normalized     `parsed` with variables also renamed to canonical letters;
      canonical_key  the orientation-independent lookup key (see canonical_key);
      order          number of operation symbols (the ETP "order");
      variables      distinct variables in first-appearance order.
    On failure (`ok=False`): `error` is "parse-failure" or "outside-fragment"
    and `reason` explains it. `input` echoes the argument in every case.
    """
    try:
        eq = parse_equation(text)
        variables: list[str] = []
        eq.lhs.variables(variables)
        eq.rhs.variables(variables)
        return {
            "input": text,
            "ok": True,
            "parsed": eq.render(),
            "normalized": normalize(eq).render(),
            "canonical_key": canonical_key(eq),
            "order": eq.size(),
            "variables": variables,
        }
    except ParseFailure as e:
        return {"input": text, "ok": False, "error": "parse-failure", "reason": str(e)}
    except OutsideFragment as e:
        return {"input": text, "ok": False, "error": "outside-fragment", "reason": str(e)}


def main() -> None:
    """CLI: parse and normalize each equation given on the command line.

    With `--json` it prints a JSON array of `analyze()` records (one per input),
    suitable for piping to another program; otherwise it prints a readable block
    per input showing the parsed form, the normalized form, order, and
    variables (or the error and reason when the input does not parse).
    """
    ap = argparse.ArgumentParser(description="parse and normalize magma equations")
    ap.add_argument("equations", nargs="+", help="equation string(s) to parse and normalize")
    ap.add_argument("--json", action="store_true",
                    help="emit a JSON array of records instead of text")
    args = ap.parse_args()

    results = [analyze(text) for text in args.equations]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    for i, r in enumerate(results):
        if i:
            print()  # blank line between blocks
        print(f"input:      {r['input']}")
        if r["ok"]:
            print(f"parsed:     {r['parsed']}")
            print(f"normalized: {r['normalized']}")
            print(f"order:      {r['order']}")
            print(f"variables:  {', '.join(r['variables'])}")
        else:
            print(f"error:      {r['error']}")
            print(f"reason:     {r['reason']}")


if __name__ == "__main__":
    main()