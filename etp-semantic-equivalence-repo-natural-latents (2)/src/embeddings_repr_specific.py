"""
embeddings_repr_specific.py -- one dedicated feature extractor PER REPRESENTATION.

The two existing schemes are:
  * generic          -- identical char n-grams for every view
  * family-specific  -- 5 tokenizers shared across the 5 families
                        (embeddings_enhanced.py)

Both treat each view as a bag of surface tokens. This scheme instead reads
each of the 19 representations with a parser written for ITS OWN syntax and
emits the structure that the syntax makes explicit:

  formal / latex / lean / confusable_vars   infix term -> tokens, (var, depth, side)
  tptp / smtlib / py_lambda                 prefix/function-call term -> head/arg tokens with depth
  py_cayley_table                           nested table[.][.] indexing -> index-nesting tokens
  ssa                                       one token per instruction: operand kinds (var/temp)
  rpn / polish                              ordered token sequence + stack-depth tags (RPN)
  slots                                     variable numbering pattern with position in the tree
  json_ast                                  exact root-to-leaf paths (=.R.◇.L.v1)
  ascii_tree                                (depth, label) lines -> parent/child label pairs
  graphviz                                  labelled edges parent -> child with child order
  text / text2 / natural_language           word n-grams, variables canonicalised
  word_problem                              only the "Claim:" sentence (the preamble is
                                            identical boilerplate for all 4,694 equations)

Shared conventions:
  * boilerplate that is identical for every equation is stripped (Lean header,
    SMT-LIB declarations, `def law(table): n = len(table)`, lambda binder, ...);
  * variables are canonicalised by first appearance (v1, v2, ...), so naming
    never matters -- including the confusable glyph names (l, I, ll, lI, ...);
  * every extractor returns a flat list of string features; sequences also
    contribute their 2- and 3-grams, so local order is kept.

Each view gets its own TF-IDF vocabulary (sublinear tf), exactly like the other
schemes, so it plugs straight into NaturalLatentResampler.
"""
import json
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

OP = '◇'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class _Canon:
    """Maps variable names to v1, v2, ... in order of first appearance."""
    def __init__(self):
        self.m = {}

    def __call__(self, name):
        if name not in self.m:
            self.m[name] = f'v{len(self.m) + 1}'
        return self.m[name]


def _ngrams(seq, ns=(2, 3)):
    out = []
    for n in ns:
        out += ['_'.join(seq[i:i + n]) for i in range(len(seq) - n + 1)]
    return out


def _seq_features(seq):
    return list(seq) + _ngrams(list(seq))


def _tree_features(tree, prefix='T'):
    """tree: ('var', name) | ('op', left, right) | ('eq', lhs, rhs)
    Emits root-to-node paths, parent/child pairs, subtree shapes, and
    (variable, depth, side) tags."""
    feats = []

    def shape(n):
        return 'v' if n[0] == 'var' else f'({shape(n[1])}{shape(n[2])})'

    def walk(n, path, depth, side):
        if n[0] == 'var':
            feats.append(f'{prefix}path:{path}.{n[1]}')
            feats.append(f'{prefix}var:{n[1]}@d{depth}{side}')
            feats.append(f'{prefix}leafdepth:{depth}{side}')
            return
        feats.append(f'{prefix}shape:{shape(n)}')
        feats.append(f'{prefix}kids:{n[1][0]}-{n[2][0]}')
        walk(n[1], path + '.L', depth + 1, side)
        walk(n[2], path + '.R', depth + 1, side)

    if tree[0] == 'eq':
        feats.append(f'{prefix}eqshape:{shape(tree[1])}={shape(tree[2])}')
        walk(tree[1], 'lhs', 0, 'l')
        walk(tree[2], 'rhs', 0, 'r')
    else:
        walk(tree, 'root', 0, '')
    return feats


# ---------------------------------------------------------------------------
# infix family: formal, latex, lean body, confusable_vars
# ---------------------------------------------------------------------------
def _parse_infix(tokens, canon):
    pos = 0

    def term():
        nonlocal pos
        t = tokens[pos]
        if t == '(':
            pos += 1
            node = expr()
            pos += 1          # ')'
            return node
        pos += 1
        return ('var', canon(t))

    def expr():
        nonlocal pos
        left = term()
        while pos < len(tokens) and tokens[pos] == OP:
            pos += 1
            left = ('op', left, term())
        return left

    return expr()


def _infix_equation_features(text, var_pattern=r'[A-Za-z]+'):
    tokens = re.findall(var_pattern + r'|[' + OP + r'=()]', text)
    canon = _Canon()
    eq = tokens.index('=')
    lhs = _parse_infix(tokens[:eq], canon)
    rhs = _parse_infix(tokens[eq + 1:], canon)
    # surface sequence with canonical vars (re-canonicalise in reading order)
    c2 = _Canon()
    seq = [c2(t) if re.fullmatch(var_pattern, t) else t for t in tokens]
    return _seq_features(seq) + _tree_features(('eq', lhs, rhs))


def feats_formal(text):
    return _infix_equation_features(text)


def feats_latex(text):
    return ['latex'] + _infix_equation_features(text.replace('\\diamond', OP))


def feats_lean(text):
    body = text.split(':=', 1)[1]
    body = body.split(',', 1)[1] if ',' in body else body
    q = re.search(r'∀([^:]*):', text)
    feats = [f'lean_nbound:{len(q.group(1).split())}'] if q else []
    return feats + _infix_equation_features(body)


def feats_confusable(text):
    # variables are strings over the confusable glyphs l / I
    return _infix_equation_features(text, var_pattern=r'[lI]+')


# ---------------------------------------------------------------------------
# function-call / prefix family: tptp, smtlib, py_lambda
# ---------------------------------------------------------------------------
def _call_features(tokens, is_var, head_names, prefix):
    """tokens of a nested prefix expression; emits (token, nesting depth) and
    sequence n-grams with canonical variables."""
    canon = _Canon()
    seq, feats, depth = [], [], 0
    for t in tokens:
        if t == '(':
            depth += 1
            continue
        if t == ')':
            depth -= 1
            continue
        if t == ',':
            continue
        tok = canon(t) if is_var(t) else ('OP' if t in head_names else t)
        seq.append(tok)
        feats.append(f'{prefix}{tok}@d{depth}')
    return feats + _seq_features(seq)


def feats_tptp(text):
    body = text.split(':', 1)[1].rsplit(')', 1)[0] if ':' in text else text
    body = body.rstrip(').')
    nb = re.search(r'!\[([^\]]*)\]', text)
    toks = re.findall(r'[A-Z][A-Za-z0-9]*|op|=|\(|\)|,', body)
    feats = [f'tptp_nbound:{len(nb.group(1).split(","))}'] if nb else []
    return feats + _call_features(toks, lambda t: t[0].isupper(), {'op'}, 'tp:')


def feats_smtlib(text):
    m = re.search(r'\(assert \(forall \(((?:\(\w+ M\)\s*)+)\)\s*(.*)\)\)\s*$', text, re.S)
    if not m:
        return _seq_features(re.findall(r'[\w=]+', text))
    nb = len(re.findall(r'\(\w+ M\)', m.group(1)))
    toks = re.findall(r'\(|\)|=|op|[a-z]\w*', m.group(2))
    return [f'smt_nbound:{nb}'] + _call_features(toks, lambda t: t not in ('op', '='), {'op'}, 'smt:')


def feats_py_lambda(text):
    binder, body = text.split(':', 1)
    params = [p.strip() for p in binder.replace('lambda', '').split(',')]
    toks = re.findall(r'==|\(|\)|,|[A-Za-z_]\w*', body)
    return [f'py_nparams:{len(params) - 1}'] + _call_features(
        toks, lambda t: t in params and t != 'op', {'op'}, 'pl:')


# ---------------------------------------------------------------------------
# py_cayley_table: nested table[a][b] indexing
# ---------------------------------------------------------------------------
def feats_py_cayley(text):
    m = re.search(r'return all\((.*?) for ', text, re.S)
    expr = m.group(1) if m else text
    nloops = len(re.findall(r'\bfor \w+ in range\(n\)', text))
    canon = _Canon()
    seq, feats, depth = [], [f'ct_nloops:{nloops}'], 0
    for t in re.findall(r'table|\[|\]|==|[a-z]\w*', expr):
        if t == '[':
            depth += 1
            continue
        if t == ']':
            depth -= 1
            continue
        tok = t if t in ('table', '==') else canon(t)
        seq.append(tok)
        feats.append(f'ct:{tok}@d{depth}')
    return feats + _seq_features(seq)


# ---------------------------------------------------------------------------
# ssa: one feature per instruction describing its operand kinds
# ---------------------------------------------------------------------------
def feats_ssa(text):
    canon = _Canon()
    feats, kinds = [], []
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for l in lines:
        if l.startswith('assert'):
            a, b = [s.strip() for s in l[len('assert'):].split('=')]
            k = f"assert:{'t' if a.startswith('t') and a[1:].isdigit() else 'v'}=" \
                f"{'t' if b.startswith('t') and b[1:].isdigit() else 'v'}"
            feats.append(k)
            kinds.append(k)
            for s in (a, b):
                if not (s.startswith('t') and s[1:].isdigit()):
                    feats.append(f'assertvar:{canon(s)}')
            continue
        dst, rhs = [s.strip() for s in l.split('=', 1)]
        a, b = [s.strip() for s in rhs.split(OP)]
        ka = 't' if a.startswith('t') and a[1:].isdigit() else 'v'
        kb = 't' if b.startswith('t') and b[1:].isdigit() else 'v'
        kinds.append(f'{ka}{OP}{kb}')
        feats.append(f'step:{ka}{OP}{kb}')
        if ka == 'v':
            feats.append(f'opnd:L:{canon(a)}')
        if kb == 'v':
            feats.append(f'opnd:R:{canon(b)}')
        if ka == 'v' and kb == 'v':
            feats.append(f'leafpair:{canon(a)}{OP}{canon(b)}')
    feats.append(f'ssa_nsteps:{len(lines) - 1}')
    return feats + _ngrams(kinds)


# ---------------------------------------------------------------------------
# rpn / polish: ordered token streams
# ---------------------------------------------------------------------------
def feats_rpn(text):
    canon = _Canon()
    seq, feats, stack = [], [], 0
    for t in text.split():
        if t in (OP, '='):
            stack -= 1
            seq.append(t)
            feats.append(f'rpn:{t}@s{stack}')
        else:
            stack += 1
            v = canon(t)
            seq.append(v)
            feats.append(f'rpn:{v}@s{stack}')
    return feats + _seq_features(seq)


def feats_polish(text):
    canon = _Canon()
    seq = [t if t in (OP, '=') else canon(t) for t in text.split()]
    # arity-tracking: how many operands are still pending when each token is read
    feats, pending = [], 1
    for t in seq:
        feats.append(f'pol:{t}@p{pending}')
        pending += 1 if t in (OP, '=') else -1
    return feats + _seq_features(seq)


# ---------------------------------------------------------------------------
# slots: variables already numbered 1..k in first-appearance order
# ---------------------------------------------------------------------------
def _slots_to_tree(x):
    if isinstance(x, list):
        return ('op', _slots_to_tree(x[0]), _slots_to_tree(x[1]))
    return ('var', f'v{x}')


def feats_slots(text):
    lhs, rhs = json.loads(text)
    tree = ('eq', _slots_to_tree(lhs), _slots_to_tree(rhs))
    flat = re.findall(r'\d+|\[|\]', text)
    return ['slots'] + _tree_features(tree, 'S') + _seq_features(flat)


# ---------------------------------------------------------------------------
# json_ast: exact paths
# ---------------------------------------------------------------------------
def feats_json_ast(text):
    canon = _Canon()

    def conv(x):
        if isinstance(x, str):
            return ('var', canon(x))
        (k, (a, b)), = x.items()
        return ('op' if k == OP else 'eq', conv(a), conv(b))

    return _tree_features(conv(json.loads(text)), 'J')


# ---------------------------------------------------------------------------
# ascii_tree: (depth, label) lines
# ---------------------------------------------------------------------------
def feats_ascii_tree(text):
    canon = _Canon()
    feats, stack = [], []          # stack of (depth, label)
    for line in text.splitlines():
        m = re.match(r'^([\s│]*)(?:[├└]── )?(.*)$', line)
        indent, label = m.group(1), m.group(2).strip()
        depth = len(indent) // 4 + (0 if line.startswith(label) else 1)
        lab = label if label in (OP, '=') else canon(label)
        branch = 'last' if '└' in line else ('mid' if '├' in line else 'root')
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else 'ROOT'
        feats += [f'at:{lab}@d{depth}', f'at:{parent}>{lab}', f'at:{branch}:{lab}']
        stack.append((depth, lab))
    return feats


# ---------------------------------------------------------------------------
# graphviz: labelled edges
# ---------------------------------------------------------------------------
def feats_graphviz(text):
    canon = _Canon()
    labels = {}
    for node, lab in re.findall(r'(n\d+) \[label="([^"]*)"\]', text):
        labels[node] = lab if lab in (OP, '=') else canon(lab)
    feats, child_idx, outdeg = [], {}, {}
    for a, b in re.findall(r'(n\d+) -> (n\d+)', text):
        k = child_idx.get(a, 0)
        child_idx[a] = k + 1
        feats.append(f'gv:{labels[a]}-{k}->{labels[b]}')
        feats.append(f'gv:{labels[a]}->{labels[b]}')
    feats.append(f'gv_nnodes:{len(labels)}')
    feats += [f'gv_node:{l}' for l in labels.values()]
    return feats


# ---------------------------------------------------------------------------
# natural-language family
# ---------------------------------------------------------------------------
_VAR_WORD = re.compile(r'^[uvwxyz]$')


def _words(text):
    canon = _Canon()
    ws = re.findall(r"[a-z]+", text.lower())
    return [canon(w) if _VAR_WORD.match(w) else w for w in ws]


def feats_text(text):
    return _seq_features(_words(text))


def feats_text2(text):
    ws = _words(text)
    # "the diamond of A and B": depth of nesting is carried by 'of' / 'and'
    return _seq_features(ws) + [f'n_of:{ws.count("of")}', f'n_and:{ws.count("and")}']


def feats_word_problem(text):
    claim = text.split('Claim:', 1)[1] if 'Claim:' in text else text
    return _seq_features(_words(claim))


def feats_natural_language(text):
    stop = {'a', 'an', 'the', 'is', 'of', 'to', 'and', 'with', 'this', 'that', 'on', 'in', 'by', 'as'}
    ws = [w for w in _words(text) if w not in stop]
    return ws + _ngrams(ws, (2,))


# ---------------------------------------------------------------------------
REPRESENTATION_EXTRACTORS = {
    'formal': feats_formal,
    'latex': feats_latex,
    'lean': feats_lean,
    'confusable_vars': feats_confusable,
    'tptp': feats_tptp,
    'smtlib': feats_smtlib,
    'py_lambda': feats_py_lambda,
    'py_cayley_table': feats_py_cayley,
    'ssa': feats_ssa,
    'rpn': feats_rpn,
    'polish': feats_polish,
    'slots': feats_slots,
    'json_ast': feats_json_ast,
    'ascii_tree': feats_ascii_tree,
    'graphviz': feats_graphviz,
    'text': feats_text,
    'text2': feats_text2,
    'word_problem': feats_word_problem,
    'natural_language': feats_natural_language,
}


def make_representation_specific_embedder(max_features=500):
    """Returns embed(texts, fit_key=view_name) -- the NaturalLatentResampler
    interface. Each view gets its own extractor and its own TF-IDF vocabulary."""
    fitted = {}

    def embed(texts, fit_key=None):
        extractor = REPRESENTATION_EXTRACTORS[fit_key]
        if fit_key not in fitted:
            fitted[fit_key] = TfidfVectorizer(analyzer=extractor, max_features=max_features,
                                              sublinear_tf=True).fit(texts)
        return fitted[fit_key].transform(texts).toarray()

    return embed


if __name__ == '__main__':
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', 'data', 'equations_representations_v2.json')) as f:
        eqs = json.load(f)
    e = next(e for e in eqs if e['node'] == 85)
    for view, fn in REPRESENTATION_EXTRACTORS.items():
        print(f'{view:18s} {fn(e[view])[:8]}')
