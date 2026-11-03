"""
Script 2: Baseline Metrics -- Cosine Similarity & Tree Edit Distance
=======================================================================
Applied PURELY to the raw equation strings themselves (e.g. "x = y \u25c7 y"),
no other representations involved. These are the two simplest possible
comparison methods, and they anchor everything else in this project: we
proved, both mathematically and empirically, that any metric satisfying
f(A,B) = f(B,A) -- which both of these do -- can NEVER distinguish
"A is stronger" from "A is weaker" (they're just A and B swapped, and a
symmetric function gives the identical number for both). Confirmed directly
in this project: 0.0% recall on the "weaker" class, exactly, every time.

That doesn't mean they're useless -- they're a fine signal for "are these
two equations similar at all" (roughly separating equivalent/incomparable),
just structurally blind to direction. Use them as a sanity-check baseline,
not as a serious classifier.

Requires: pip install scikit-learn zss
"""
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ---------------------------------------------------------------------------
# Cosine similarity, purely on equation text
# ---------------------------------------------------------------------------
def cosine_similarity_equations(equation_a, equation_b, char_ngrams=(2, 4)):
    """
    Character n-gram TF-IDF cosine similarity between two raw equation
    strings. Character-level (not word-level) tokenization was found, in
    this project's own head-to-head test, to substantially outperform
    word-level on every downstream diagnostic -- it preserves operator
    symbols and bracket nesting that word-level tokenization discards.
    """
    vec = TfidfVectorizer(analyzer='char', ngram_range=char_ngrams).fit([equation_a, equation_b])
    X = vec.transform([equation_a, equation_b]).toarray()
    return float(cosine_similarity(X[0:1], X[1:2])[0, 0])


# ---------------------------------------------------------------------------
# Tree edit distance, purely on parsed equation structure
# ---------------------------------------------------------------------------
def tokenize(s):
    return re.findall(r'[A-Za-z]+|[\u25c7=()]', s)


def parse_term(toks, pos):
    if toks[pos] == '(':
        node, pos = parse_expr(toks, pos + 1)
        assert toks[pos] == ')'
        return node, pos + 1
    return ('var', toks[pos]), pos + 1


def parse_expr(toks, pos):
    left, pos = parse_term(toks, pos)
    if pos < len(toks) and toks[pos] == '\u25c7':
        right, pos = parse_term(toks, pos + 1)
        return ('op', left, right), pos
    return left, pos


def parse_equation(s):
    toks = tokenize(s)
    eq = toks.index('=')
    lhs, _ = parse_expr(toks[:eq], 0)
    rhs, _ = parse_expr(toks[eq + 1:], 0)
    return ('eq', lhs, rhs)


def _to_zss_node(node):
    from zss import Node
    if node[0] == 'var':
        return Node(node[1])
    elif node[0] == 'op':
        n = Node('\u25c7')
        n.addkid(_to_zss_node(node[1]))
        n.addkid(_to_zss_node(node[2]))
        return n
    elif node[0] == 'eq':
        n = Node('=')
        n.addkid(_to_zss_node(node[1]))
        n.addkid(_to_zss_node(node[2]))
        return n


def _tree_size(node):
    return 1 + sum(_tree_size(c) for c in node.children)


def tree_edit_distance_equations(equation_a, equation_b, normalized=True):
    """
    Zhang-Shasha tree edit distance between the two equations' parsed ASTs.
    This is symmetric (dist(A,B) = dist(B,A)) by definition of tree edit
    distance -- same direction-blindness as cosine, for a different
    mathematical reason (edit scripts can always be run in reverse).

    If normalized=True, returns a SIMILARITY in [0,1]:
        Sim(A,B) = 1 - TED(A,B) / (|A| + |B|)
    """
    from zss import simple_distance
    tree_a = _to_zss_node(parse_equation(equation_a))
    tree_b = _to_zss_node(parse_equation(equation_b))
    ted = simple_distance(tree_a, tree_b, get_children=lambda n: n.children,
                           get_label=lambda n: n.label,
                           label_dist=lambda x, y: 0 if x == y else 1)
    if not normalized:
        return ted
    size_a, size_b = _tree_size(tree_a), _tree_size(tree_b)
    return 1 - ted / (size_a + size_b)


if __name__ == '__main__':
    pairs = [
        ("x = x \u25c7 x", "x = x \u25c7 x"),
        ("x \u25c7 y = y \u25c7 x", "x = x"),
        ("x = y \u25c7 (y \u25c7 x)", "x = (x \u25c7 y) \u25c7 y"),
    ]
    for a, b in pairs:
        cos = cosine_similarity_equations(a, b)
        ted_sim = tree_edit_distance_equations(a, b, normalized=True)
        print(f"A: {a}\nB: {b}\n  cosine_similarity={cos:.3f}   tree_edit_similarity={ted_sim:.3f}\n")
