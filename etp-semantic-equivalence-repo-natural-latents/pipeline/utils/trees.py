"""
Representation-native structures and edit distances.

Each representation is read with a parser for ITS OWN syntax, so the edit
distance compares what that representation actually encodes:

  tree representations  -> ordered labelled tree, Zhang-Shasha tree edit
                           distance (unit costs, `edist` C implementation)
      formal, latex, confusable_vars  infix term tree
      lean                            forall-binder node over the infix tree
      tptp                            '!' binder node over the op(.,.) term tree
      smtlib                          full s-expression tree of the (assert ...)
      py_lambda, py_cayley_table      Python AST (ast.parse)
      json_ast                        JSON object tree
      slots                           nested-list tree
      ascii_tree                      tree rebuilt from indentation
      graphviz                        tree rebuilt from the labelled edges
  sequence representations -> token sequence, Levenshtein distance (rapidfuzz)
      rpn, polish                     operator/variable tokens
      ssa                             instruction tokens
      text, text2, natural_language, word_problem   word tokens

Distances are normalised into a SIMILARITY in [0, 1]:
    sim(A, B) = 1 - dist(A, B) / (size(A) + size(B))
Both distances are symmetric, so sim(A, B) == sim(B, A).
"""
import ast
import json
import re

import numpy as np
from edist.ted import standard_ted
from rapidfuzz.distance import Levenshtein

OP = '◇'


class Tree:
    """Ordered labelled tree in edist's (nodes, adjacency) format."""
    __slots__ = ('nodes', 'adj')

    def __init__(self):
        self.nodes, self.adj = [], []

    def add(self, label, parent=None):
        self.nodes.append(str(label))
        self.adj.append([])
        idx = len(self.nodes) - 1
        if parent is not None:
            self.adj[parent].append(idx)
        return idx

    def __len__(self):
        return len(self.nodes)


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------
def _infix_tree(text, var_pattern=r'[A-Za-z]+', tree=None, parent=None):
    toks = re.findall(var_pattern + r'|[' + OP + r'=()]', text)
    t = tree or Tree()
    pos = 0

    def term(par):
        nonlocal pos
        if toks[pos] == '(':
            pos += 1
            node = expr(par)
            pos += 1
            return node
        pos += 1
        return ('v', toks[pos - 1])

    def expr(par):
        nonlocal pos
        left = term(par)
        while pos < len(toks) and toks[pos] == OP:
            pos += 1
            left = ('op', left, term(par))
        return left

    def emit(node, par):
        if node[0] == 'v':
            t.add(node[1], par)
        else:
            k = t.add(OP, par)
            emit(node[1], k)
            emit(node[2], k)

    eq = toks.index('=')
    lhs_toks, rhs_toks = toks[:eq], toks[eq + 1:]
    root = t.add('=', parent)
    for side in (lhs_toks, rhs_toks):
        toks, pos = side, 0
        emit(expr(root), root)
    return t


def tree_formal(text):
    return _infix_tree(text)


def tree_latex(text):
    return _infix_tree(text.replace('\\diamond', OP))


def tree_confusable(text):
    return _infix_tree(text, var_pattern=r'[lI]+')


def tree_lean(text):
    t = Tree()
    q = re.search('∀([^:]*):', text)
    root = t.add('∀')
    for v in (q.group(1).split() if q else []):
        t.add(v, root)
    body = text.split(':=', 1)[1]
    body = body.split(',', 1)[1] if ',' in body else body
    return _infix_tree(body, tree=t, parent=root)


def _call_tree(tokens, t, parent):
    """tokens of  f(a, g(b, c))  style terms."""
    pos = 0

    def term(par):
        nonlocal pos
        name = tokens[pos]
        pos += 1
        k = t.add(name, par)
        if pos < len(tokens) and tokens[pos] == '(':
            pos += 1
            while tokens[pos] != ')':
                if tokens[pos] == ',':
                    pos += 1
                    continue
                term(k)
            pos += 1
        return k

    term(parent)


def tree_tptp(text):
    t = Tree()
    root = t.add('!')
    nb = re.search(r'!\[([^\]]*)\]', text)
    for v in (nb.group(1).split(',') if nb else []):
        t.add(v.strip(), root)
    body = text.split(':', 1)[1].strip()
    body = re.sub(r'\)\s*\.\s*$', '', body)
    lhs, rhs = body.split('=', 1)
    eq = t.add('=', root)
    for side in (lhs, rhs):
        _call_tree(re.findall(r'\w+|\(|\)|,', side), t, eq)
    return t


def _sexpr(tokens, pos, t, parent):
    """tokens start at '(' -> node labelled by the head atom (or '()' for a list of lists)."""
    pos += 1
    if tokens[pos] not in ('(', ')'):
        k = t.add(tokens[pos], parent)
        pos += 1
    else:
        k = t.add('()', parent)
    while tokens[pos] != ')':
        if tokens[pos] == '(':
            pos = _sexpr(tokens, pos, t, k)
        else:
            t.add(tokens[pos], k)
            pos += 1
    return pos + 1


def tree_smtlib(text):
    m = re.search(r'\(assert.*', text, re.S)
    tokens = re.findall(r'\(|\)|[^\s()]+', m.group(0) if m else text)
    t = Tree()
    _sexpr(tokens, 0, t, None)
    return t


def tree_python(text):
    t = Tree()

    def walk(node, par):
        if isinstance(node, (ast.Load, ast.Store)):
            return
        if isinstance(node, ast.Name):
            label = f'Name:{node.id}'
        elif isinstance(node, ast.arg):
            label = f'arg:{node.arg}'
        elif isinstance(node, ast.Constant):
            label = f'Const:{node.value!r}'
        elif isinstance(node, ast.FunctionDef):
            label = f'def:{node.name}'
        else:
            label = type(node).__name__
        k = t.add(label, par)
        for c in ast.iter_child_nodes(node):
            walk(c, k)

    walk(ast.parse(text.strip()), None)
    return t


def tree_json_ast(text):
    t = Tree()

    def walk(x, par):
        if isinstance(x, str):
            t.add(x, par)
            return
        (key, kids), = x.items()
        k = t.add(key, par)
        for c in kids:
            walk(c, k)

    walk(json.loads(text), None)
    return t


def tree_slots(text):
    t = Tree()

    def walk(x, par):
        if isinstance(x, list):
            k = t.add('[]', par)
            for c in x:
                walk(c, k)
        else:
            t.add(str(x), par)

    walk(json.loads(text), None)
    return t


def tree_ascii(text):
    t = Tree()
    stack = []                                  # (depth, node index)
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r'^([\s│]*)((?:[├└]── )?)(.*)$', line)
        depth = len(m.group(1)) // 4 + (1 if m.group(2) else 0)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        k = t.add(m.group(3).strip(), stack[-1][1] if stack else None)
        stack.append((depth, k))
    return t


def tree_graphviz(text):
    labels = dict(re.findall(r'(n\d+) \[label="([^"]*)"\]', text))
    edges = re.findall(r'(n\d+) -> (n\d+)', text)
    kids, has_parent = {}, set()
    for a, b in edges:
        kids.setdefault(a, []).append(b)
        has_parent.add(b)
    t = Tree()

    def walk(n, par):
        k = t.add(labels[n], par)
        for c in kids.get(n, []):
            walk(c, k)

    for root in [n for n in labels if n not in has_parent]:
        walk(root, None)
    return t


def seq_tokens(text):
    return text.split()


def seq_words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


TREE_PARSERS = {
    'formal': tree_formal, 'latex': tree_latex, 'lean': tree_lean,
    'confusable_vars': tree_confusable, 'tptp': tree_tptp, 'smtlib': tree_smtlib,
    'py_lambda': tree_python, 'py_cayley_table': tree_python,
    'json_ast': tree_json_ast, 'slots': tree_slots,
    'ascii_tree': tree_ascii, 'graphviz': tree_graphviz,
}
SEQUENCE_PARSERS = {
    'rpn': seq_tokens, 'polish': seq_tokens, 'ssa': seq_tokens,
    'text': seq_words, 'text2': seq_words, 'natural_language': seq_words, 'word_problem': seq_words,
}


def parse_representation(view, text):
    if view in TREE_PARSERS:
        return TREE_PARSERS[view](text)
    return SEQUENCE_PARSERS[view](text)


def edit_similarity(a, b):
    """Normalised similarity between two parsed structures of the same view."""
    if isinstance(a, Tree):
        d = standard_ted(a.nodes, a.adj, b.nodes, b.adj)
    else:
        d = Levenshtein.distance(a, b)
    return 1.0 - d / max(len(a) + len(b), 1)


def pairwise_edit_similarity(parsed, ii, jj):
    """parsed: list of structures (one per equation) -> similarity per pair,
    computed once per unordered pair (the measure is symmetric)."""
    cache, out = {}, np.empty(len(ii))
    for k, (i, j) in enumerate(zip(ii, jj)):
        key = (i, j) if i < j else (j, i)
        if key not in cache:
            cache[key] = edit_similarity(parsed[key[0]], parsed[key[1]])
        out[k] = cache[key]
    return out
