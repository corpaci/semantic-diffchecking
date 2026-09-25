"""
advanced_metrics.py -- Additional sophisticated metrics for equation comparison.

Includes:
1. Wasserstein (Optimal Transport) distance - both symmetric and directional
2. Algebraic property extraction and comparison
3. Normalized Compression Distance (NCD)
4. Enhanced edit script features
5. Tree convolution kernel
"""
import numpy as np
import zlib
import re
from scipy.spatial.distance import cdist
from scipy.stats import wasserstein_distance
try:
    import ot  # POT: Python Optimal Transport
    HAS_OT = True
except ImportError:
    HAS_OT = False


# =============================================================================
# 1. WASSERSTEIN DISTANCE (Optimal Transport)
# =============================================================================

def wasserstein_matrix_1d(latents):
    """
    Symmetric Wasserstein distance treating each latent vector as a 1D distribution.
    More geometrically meaningful than KL divergence.
    """
    N, d = latents.shape
    W = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        # Treat latent vector as weights on positions 0, 1, 2, ..., d-1
        a = np.abs(latents[i]) + 1e-8
        a = a / a.sum()

        for j in range(i, N):
            b = np.abs(latents[j]) + 1e-8
            b = b / b.sum()

            # Wasserstein-1 distance on 1D grid
            dist = wasserstein_distance(np.arange(d), np.arange(d), a, b)
            W[i, j] = dist
            W[j, i] = dist  # symmetric

    return W


def earth_movers_directional(latents, reg=0.05):
    """
    Directional variant using entropic regularization.
    The "effort" to move distribution A to match B can differ from B to A
    due to unbalanced mass (allowing creation/destruction).
    """
    if not HAS_OT:
        print("Warning: POT library not installed. Falling back to symmetric Wasserstein.")
        return wasserstein_matrix_1d(latents)

    N, d = latents.shape
    W = np.zeros((N, N), dtype=np.float64)

    # Ground metric: Euclidean distance between dimensions
    positions = np.arange(d).reshape(-1, 1)
    M = cdist(positions, positions, metric='euclidean')

    for i in range(N):
        a = np.abs(latents[i]) + 1e-8
        a = a / a.sum()

        for j in range(N):
            if i == j:
                W[i, j] = 0.0
                continue

            b = np.abs(latents[j]) + 1e-8
            b = b / b.sum()

            # Sinkhorn with entropic regularization (directional due to numerical asymmetry)
            try:
                W[i, j] = ot.sinkhorn2(a, b, M, reg)
            except:
                # Fallback to symmetric if Sinkhorn fails
                W[i, j] = wasserstein_distance(np.arange(d), np.arange(d), a, b)

    return W


# =============================================================================
# 2. ALGEBRAIC PROPERTY FEATURES
# =============================================================================

def extract_algebraic_properties(formal_expr):
    """
    Extract semantic properties from the formal equation string.
    Returns a feature dictionary.
    """
    expr = formal_expr.strip()

    # Split into LHS and RHS
    if '=' in expr:
        lhs, rhs = expr.split('=', 1)
    else:
        lhs, rhs = expr, ""

    props = {}

    # Variable counts
    props['count_x'] = expr.count('x')
    props['count_y'] = expr.count('y')
    props['count_z'] = expr.count('z')
    props['total_vars'] = props['count_x'] + props['count_y'] + props['count_z']

    # Operator count (◇ symbol)
    props['count_op'] = expr.count('◇') + expr.count('◊')

    # Nesting depth (count parentheses)
    props['max_depth'] = max_paren_depth(expr)

    # LHS complexity
    props['lhs_is_single_var'] = lhs.strip() in ['x', 'y', 'z']
    props['lhs_has_op'] = '◇' in lhs or '◊' in lhs

    # Symmetry hints (variable order)
    vars_in_order = re.findall(r'[xyz]', expr)
    props['has_xy_pattern'] = 'xy' in ''.join(vars_in_order)
    props['has_yx_pattern'] = 'yx' in ''.join(vars_in_order)
    props['symmetric_hint'] = props['has_xy_pattern'] and props['has_yx_pattern']

    # Unique variable count
    props['unique_vars'] = len(set(c for c in expr if c in 'xyz'))

    # Expression length (complexity proxy)
    props['expr_length'] = len(expr.replace(' ', ''))

    return props


def max_paren_depth(expr):
    """Count maximum nesting depth of parentheses."""
    depth = 0
    max_depth = 0
    for char in expr:
        if char == '(':
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ')':
            depth -= 1
    return max_depth


def algebraic_property_vector(properties):
    """Convert property dict to feature vector."""
    keys = ['count_x', 'count_y', 'count_z', 'total_vars', 'count_op',
            'max_depth', 'lhs_is_single_var', 'lhs_has_op', 'symmetric_hint',
            'unique_vars', 'expr_length']
    return np.array([float(properties.get(k, 0)) for k in keys])


def algebraic_similarity_matrix(equations_dict):
    """
    Compute similarity based on algebraic properties.
    Returns both symmetric (cosine) and directional (subsumption) matrices.
    """
    node_ids = sorted(equations_dict.keys())
    N = len(node_ids)

    # Extract properties
    props = {nid: extract_algebraic_properties(equations_dict[nid]) for nid in node_ids}
    vectors = np.array([algebraic_property_vector(props[nid]) for nid in node_ids])

    # Symmetric: cosine similarity on property vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8
    normalized = vectors / norms
    cosine_sim = normalized @ normalized.T

    # Directional: property subsumption score
    # "Does A have all properties that B has?" (A might be more general)
    subsumption = np.zeros((N, N), dtype=np.float64)
    for i in range(N):
        for j in range(N):
            # Count how many of j's properties are matched by i
            prop_i = props[node_ids[i]]
            prop_j = props[node_ids[j]]

            matches = sum(1 for k in prop_i if prop_i.get(k) == prop_j.get(k))
            subsumption[i, j] = matches / max(len(prop_i), 1)

    return cosine_sim, subsumption


# =============================================================================
# 3. NORMALIZED COMPRESSION DISTANCE
# =============================================================================

def normalized_compression_distance_matrix(texts):
    """
    NCD using gzip compression as a proxy for Kolmogorov complexity.
    Symmetric by construction.
    """
    N = len(texts)

    # Pre-compute individual compressed sizes
    compressed_sizes = [len(zlib.compress(txt.encode('utf-8'), level=9)) for txt in texts]

    ncd = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        for j in range(i, N):
            if i == j:
                ncd[i, j] = 0.0
            else:
                # Compress concatenation
                combined = texts[i] + texts[j]
                c_combined = len(zlib.compress(combined.encode('utf-8'), level=9))

                # NCD formula
                c_i, c_j = compressed_sizes[i], compressed_sizes[j]
                ncd[i, j] = (c_combined - min(c_i, c_j)) / max(c_i, c_j)
                ncd[j, i] = ncd[i, j]  # symmetric

    return ncd


def compression_gain_directional(texts):
    """
    Directional: how much does knowing A help compress B?
    gain[i,j] = "does prepending text_i help compress text_j?"
    """
    N = len(texts)

    compressed_sizes = [len(zlib.compress(txt.encode('utf-8'), level=9)) for txt in texts]
    gain = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        for j in range(N):
            if i == j:
                gain[i, j] = 0.0
            else:
                # Compress j alone vs compress (i+j)
                c_j = compressed_sizes[j]
                c_ij = len(zlib.compress((texts[i] + texts[j]).encode('utf-8'), level=9))

                # Gain: how much did prepending i reduce j's compressed size?
                # Normalize by j's original size
                gain[i, j] = (c_j - (c_ij - compressed_sizes[i])) / c_j

    return gain


# =============================================================================
# 4. ENHANCED EDIT SCRIPT FEATURES
# =============================================================================

def extract_edit_operations(formal_a, formal_b):
    """
    Extract types of edits needed to transform A to B.
    Returns feature vector based on edit operations.
    """
    # Simple heuristic-based edit classification
    # (Full tree edit distance with script extraction would require AST parsing)

    features = {}

    # Character-level differences
    features['levenshtein_dist'] = levenshtein_distance(formal_a, formal_b)

    # Token differences
    tokens_a = set(re.findall(r'[a-zA-Z◇◊]+|\d+|[()=]', formal_a))
    tokens_b = set(re.findall(r'[a-zA-Z◇◊]+|\d+|[()=]', formal_b))

    features['tokens_added'] = len(tokens_b - tokens_a)
    features['tokens_removed'] = len(tokens_a - tokens_b)
    features['tokens_shared'] = len(tokens_a & tokens_b)

    # Variable renaming detection
    vars_a = sorted(c for c in formal_a if c in 'xyz')
    vars_b = sorted(c for c in formal_b if c in 'xyz')
    features['var_permutation'] = int(set(vars_a) == set(vars_b) and vars_a != vars_b)

    # Depth change
    features['depth_change'] = abs(max_paren_depth(formal_a) - max_paren_depth(formal_b))

    # Length change
    features['length_ratio'] = len(formal_b) / (len(formal_a) + 1)

    return features


def levenshtein_distance(s1, s2):
    """Standard Levenshtein edit distance."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def edit_script_feature_matrix(equations_dict, node_order, ii, jj):
    """
    Compute edit features for each pair in (ii, jj).
    Returns (N_pairs, N_features) matrix.
    """
    features_list = []

    for idx_i, idx_j in zip(ii, jj):
        node_i = node_order[idx_i]
        node_j = node_order[idx_j]

        formal_i = equations_dict.get(node_i, "")
        formal_j = equations_dict.get(node_j, "")

        feats = extract_edit_operations(formal_i, formal_j)
        features_list.append([
            feats['levenshtein_dist'],
            feats['tokens_added'],
            feats['tokens_removed'],
            feats['tokens_shared'],
            feats['var_permutation'],
            feats['depth_change'],
            feats['length_ratio'],
        ])

    return np.array(features_list, dtype=np.float64)


# =============================================================================
# 5. TREE CONVOLUTION KERNEL
# =============================================================================

def extract_subtree_patterns(formal_expr):
    """
    Extract all subtree patterns from the expression.
    Simple pattern-based extraction (not full AST parsing).
    """
    patterns = set()

    # Add the full expression
    patterns.add(formal_expr.strip())

    # Extract all parenthesized sub-expressions
    depth = 0
    start = -1
    for i, char in enumerate(formal_expr):
        if char == '(':
            if depth == 0:
                start = i
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0 and start >= 0:
                patterns.add(formal_expr[start:i+1])

    # Extract all operator applications
    # Pattern: "var ◇ var" or "(expr) ◇ (expr)"
    op_patterns = re.findall(r'[a-z(][^◇]*◇[^◇]*[a-z)]', formal_expr)
    patterns.update(op_patterns)

    # Extract variable occurrences
    patterns.update(re.findall(r'[xyz]', formal_expr))

    return patterns


def tree_kernel_matrix(equations_dict, node_order):
    """
    Compute tree convolution kernel: count shared subtree patterns.
    Symmetric similarity measure.
    """
    N = len(node_order)

    # Extract patterns for all equations
    all_patterns = {}
    for node_id in node_order:
        all_patterns[node_id] = extract_subtree_patterns(equations_dict[node_id])

    kernel = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        node_i = node_order[i]
        patterns_i = all_patterns[node_i]

        for j in range(i, N):
            node_j = node_order[j]
            patterns_j = all_patterns[node_j]

            # Count shared patterns
            shared = len(patterns_i & patterns_j)
            norm = np.sqrt(len(patterns_i) * len(patterns_j)) + 1e-8

            kernel[i, j] = shared / norm
            kernel[j, i] = kernel[i, j]

    return kernel


# =============================================================================
# CONVENIENCE FUNCTIONS FOR NOTEBOOK INTEGRATION
# =============================================================================

ADVANCED_METRICS = {
    'Wasserstein': wasserstein_matrix_1d,
    'WassersteinDirectional': earth_movers_directional,
    'CompressionNCD': normalized_compression_distance_matrix,
    'CompressionGain': compression_gain_directional,
}


def compute_advanced_metric(latents, metric_name):
    """
    Compute a single advanced metric.
    latents: (N, d) array
    metric_name: one of ADVANCED_METRICS keys
    Returns: (N, N) distance/divergence matrix
    """
    if metric_name not in ADVANCED_METRICS:
        raise ValueError(f"Unknown metric: {metric_name}")

    return ADVANCED_METRICS[metric_name](latents)
