"""
wl_features.py -- Weisfeiler-Lehman subtree features for equations.

Reference: Shervashidze et al., "Weisfeiler-Lehman Graph Kernels", JMLR 12 (2011).

Each equation's term tree (parsed from the 'formal' view) is relabelled for
`h` rounds: a node's new label is its old label followed by its children's
old labels, in order. After round k a label describes the node's whole
subtree down to depth k. The feature vector of an equation counts every label
seen in rounds 0..h -- a bag of subtree patterns.

Conventions:
  * variables are canonicalised by first appearance (v1, v2, ...), so renaming
    never matters;
  * the two sides of '=' are unordered (a = b is the same law as b = a), so
    the root combines its children's labels in sorted order;
  * '◇' is NOT commutative, so its children keep their order (left, right).

The usual WL *kernel* is the dot product f(A).f(B), which is symmetric and
therefore direction-blind. For the stronger/weaker task feed the vectors
themselves, e.g. [f(A), f(B), f(A) - f(B)], to a classifier.

Requires: numpy, scikit-learn.
"""
from collections import Counter

import numpy as np
from sklearn.feature_extraction import DictVectorizer

from magma_fingerprints import parse_equation

OP = '◇'


def _flatten(lhs, rhs):
    canon = {}
    labels, children = ['='], [[]]

    def add(node):
        idx = len(labels)
        if node[0] == 'var':
            labels.append(canon.setdefault(node[1], f'v{len(canon) + 1}'))
            children.append([])
        else:
            labels.append(OP)
            children.append([])
            children[idx] = [add(node[1]), add(node[2])]
        return idx

    children[0] = [add(lhs), add(rhs)]
    return labels, children


def _to_nodes(formal):
    """Flatten the parsed equation into (label, children) lists; node 0 is '='.
    Variables are numbered by first appearance, which depends on which side is
    read first, so both orientations are built and the lexicographically
    smaller one is kept (same idea as oracle/mapper.py's canonical key)."""
    lhs, rhs = parse_equation(formal)
    return min(_flatten(lhs, rhs), _flatten(rhs, lhs), key=lambda t: t[0])


def wl_labels(formal, h=4):
    """All WL labels of one equation, rounds 0..h (with repeats, for counting)."""
    labels, children = _to_nodes(formal)
    out = [f'0:{l}' for l in labels]
    cur = labels
    for k in range(1, h + 1):
        new = []
        for i, lab in enumerate(cur):
            kids = [cur[c] for c in children[i]]
            if i == 0:
                kids = sorted(kids)              # '=' is symmetric
            new.append(f'{lab}({",".join(kids)})' if kids else lab)
        cur = new
        out += [f'{k}:{l}' for i, l in enumerate(cur) if children[i]]   # leaves don't change
    return out


class WLFeaturizer:
    """Fit a WL-label vocabulary on a set of equations, then map equations to
    count vectors. Labels seen in fewer than `min_count` fitted equations are
    dropped (rare full-equation labels would only memorise individual laws)."""

    def __init__(self, h=4, min_count=3):
        self.h, self.min_count = h, min_count

    def fit(self, formals):
        df = Counter(l for f in formals for l in set(wl_labels(f, self.h)))
        keep = {l for l, c in df.items() if c >= self.min_count}
        self.vec = DictVectorizer(sparse=False).fit([{l: 1 for l in keep}])
        self.feature_names_ = self.vec.get_feature_names_out()
        return self

    def transform(self, formals):
        vocab = self.vec.vocabulary_
        return self.vec.transform([{l: c for l, c in Counter(wl_labels(f, self.h)).items() if l in vocab}
                                   for f in formals])

    def fit_transform(self, formals):
        return self.fit(formals).transform(formals)


def pair_features(W, I, J):
    """Directional pair features [f(A), f(B), f(A) - f(B)] for index arrays I, J."""
    return np.concatenate([W[I], W[J], W[I] - W[J]], axis=1)


if __name__ == '__main__':
    for lab in wl_labels('x = y ◇ (x ◇ y)', h=2):
        print(lab)
