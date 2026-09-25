"""
symmetric_methods.py -- Symmetric distance/similarity measures for semantic equivalence.

MATHEMATICAL PROPERTY: All functions here satisfy f(A, B) = f(B, A) exactly.
Therefore, they provably CANNOT distinguish "stronger" from "weaker" --
symmetry implies identical scores regardless of direction, making the
relation label unrecoverable from the score alone.

This module is included for:
1. DOCUMENTATION: proving symmetry empirically, not just theoretically
2. BASELINE: comparing against directional methods
3. NEGATIVE CONTROL: validating that the evaluation detects the limitation

Implemented measures:
  - Euclidean distance
  - Cosine similarity
  - Jensen-Shannon divergence (symmetric KL)
  - Bhattacharyya distance
  - Hellinger distance
  - Wasserstein distance (1D approximation)
  - Maximum Mean Discrepancy (MMD)
"""
import numpy as np
from scipy.spatial.distance import cdist, pdist, squareform
from scipy.stats import entropy


def euclidean_distance_matrix(latents):
    """Euclidean L2 distance -- symmetric by definition.

    d(A, B) = sqrt(sum((A_i - B_i)^2)) = d(B, A)
    """
    dist = cdist(latents, latents, metric='euclidean')
    assert np.allclose(dist, dist.T), "Euclidean distance must be symmetric"
    return dist


def cosine_similarity_matrix(latents):
    """Cosine similarity -- symmetric by definition.

    cos(A, B) = (A · B) / (||A|| ||B||) = cos(B, A)
    Returned as a signed matrix where higher values indicate more similarity.
    """
    latents_norm = latents / (np.linalg.norm(latents, axis=1, keepdims=True) + 1e-10)
    sim = np.dot(latents_norm, latents_norm.T)
    assert np.allclose(sim, sim.T), "Cosine similarity must be symmetric"
    return sim


def jensen_shannon_divergence_matrix(latents, k=10):
    """Symmetric version of KL divergence.

    JS(P || Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M), where M = (P + Q) / 2
    JS(P || Q) = JS(Q || P) by construction.
    """
    # Convert latents to probability distributions via local Gaussians
    mu, var = _build_local_gaussians(latents, k=k)
    N = mu.shape[0]
    js = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        for j in range(i, N):
            mu_i, var_i = mu[i], var[i]
            mu_j, var_j = mu[j], var[j]

            # Midpoint distribution
            mu_m = 0.5 * (mu_i + mu_j)
            var_m = 0.5 * (var_i + var_j)

            # KL(i || m)
            kl_im = 0.5 * np.sum(np.log(var_m / var_i) - 1 + var_i / var_m + (mu_i - mu_m) ** 2 / var_m)

            # KL(j || m)
            kl_jm = 0.5 * np.sum(np.log(var_m / var_j) - 1 + var_j / var_m + (mu_j - mu_m) ** 2 / var_m)

            js_ij = 0.5 * (kl_im + kl_jm)
            js[i, j] = js_ij
            js[j, i] = js_ij  # Explicitly symmetric

    assert np.allclose(js, js.T), "Jensen-Shannon divergence must be symmetric"
    return js


def bhattacharyya_distance_matrix(latents, k=10):
    """Bhattacharyya distance between Gaussian distributions.

    DB(P || Q) = 0.125 * log(0.125 * (σ_P^2/σ_Q^2 + σ_Q^2/σ_P^2 + 2)) + 0.5 * log(det(Σ_avg) / sqrt(det(Σ_P) det(Σ_Q)))

    Symmetric: DB(P || Q) = DB(Q || P)
    """
    mu, var = _build_local_gaussians(latents, k=k)
    N = mu.shape[0]
    db = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        for j in range(i, N):
            mu_i, var_i = mu[i], var[i]
            mu_j, var_j = mu[j], var[j]

            # Simplified Bhattacharyya for diagonal covariance
            # db = 0.125 * sum(log(var_avg / sqrt(var_i * var_j))) + 0.125 * sum((mu_i - mu_j)^2 / var_avg)
            var_avg = 0.5 * (var_i + var_j)
            term1 = 0.125 * np.sum(np.log(var_avg / np.sqrt(var_i * var_j + 1e-12)))
            term2 = 0.125 * np.sum((mu_i - mu_j) ** 2 / (var_avg + 1e-12))

            db_ij = term1 + term2
            db[i, j] = db_ij
            db[j, i] = db_ij  # Explicitly symmetric

    assert np.allclose(db, db.T), "Bhattacharyya distance must be symmetric"
    return db


def hellinger_distance_matrix(latents, k=10):
    """Hellinger distance -- symmetric measure of dissimilarity.

    H(P, Q) = sqrt(0.5 * sum((sqrt(P) - sqrt(Q))^2))

    H(P, Q) = H(Q, P) by definition.
    """
    mu, var = _build_local_gaussians(latents, k=k)
    N = mu.shape[0]
    h = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        for j in range(i, N):
            mu_i, var_i = mu[i], var[i]
            mu_j, var_j = mu[j], var[j]

            # Hellinger distance for Gaussians
            var_avg = 0.5 * (var_i + var_j)
            term1 = 0.25 * np.sum((mu_i - mu_j) ** 2 / var_avg)
            term2 = 0.5 * np.sum(np.log(var_avg / np.sqrt(var_i * var_j + 1e-12)))

            h_ij = np.sqrt(np.clip(1 - np.exp(-term1 - 0.5 * term2), 0, 1))
            h[i, j] = h_ij
            h[j, i] = h_ij  # Explicitly symmetric

    assert np.allclose(h, h.T), "Hellinger distance must be symmetric"
    return h


def wasserstein_distance_matrix(latents):
    """1-D Wasserstein (Earth Mover's) distance on marginals.

    W(P, Q) = integral |CDF_P(x) - CDF_Q(x)| dx

    W(P, Q) = W(Q, P) by definition.
    """
    N, d = latents.shape
    w = np.zeros((N, N), dtype=np.float64)

    # Compute Wasserstein distance on each dimension, then average
    for i in range(N):
        for j in range(i, N):
            dists = []
            for dim in range(d):
                x_i = np.sort(latents[i, dim:dim+1] * 1000)  # Rough approximation
                x_j = np.sort(latents[j, dim:dim+1] * 1000)
                # Simplified: L2 distance on sorted coordinates
                w_1d = np.sqrt(((x_i - x_j) ** 2).mean())
                dists.append(w_1d)

            w_ij = np.mean(dists)
            w[i, j] = w_ij
            w[j, i] = w_ij  # Explicitly symmetric

    assert np.allclose(w, w.T), "Wasserstein distance must be symmetric"
    return w


def mmd_matrix(latents, kernel='rbf', gamma=1.0):
    """Maximum Mean Discrepancy (MMD) -- symmetric kernel-based distance.

    MMD(P, Q) = || mean_P(phi(x)) - mean_Q(phi(x)) ||_H

    MMD(P, Q) = MMD(Q, P) by definition (symmetric kernel).
    """
    N = latents.shape[0]
    mmd = np.zeros((N, N), dtype=np.float64)

    for i in range(N):
        for j in range(i, N):
            # Kernel distance between two points
            if kernel == 'rbf':
                k_ii = np.exp(-gamma * np.sum((latents[i] - latents[i]) ** 2))
                k_jj = np.exp(-gamma * np.sum((latents[j] - latents[j]) ** 2))
                k_ij = np.exp(-gamma * np.sum((latents[i] - latents[j]) ** 2))
            else:  # polynomial or linear
                k_ii = 1.0
                k_jj = 1.0
                k_ij = np.dot(latents[i], latents[j]) / (np.linalg.norm(latents[i]) * np.linalg.norm(latents[j]) + 1e-10)

            mmd_ij = np.sqrt(np.clip(k_ii + k_jj - 2 * k_ij, 0, None))
            mmd[i, j] = mmd_ij
            mmd[j, i] = mmd_ij  # Explicitly symmetric

    assert np.allclose(mmd, mmd.T), "MMD must be symmetric"
    return mmd


def _build_local_gaussians(latents, k=10):
    """Helper: fit local Gaussian parameters via k-NN for symmetric methods."""
    from sklearn.neighbors import NearestNeighbors

    N, d = latents.shape
    k = min(k, N - 1)
    nn = NearestNeighbors(n_neighbors=k + 1).fit(latents)
    _, neighbor_idx = nn.kneighbors(latents)
    neighbor_idx = neighbor_idx[:, 1:]

    variances = np.zeros((N, d), dtype=np.float64)
    for i in range(N):
        variances[i] = latents[neighbor_idx[i]].var(axis=0) + 1e-3

    return latents.astype(np.float64), variances


def verify_symmetry(matrix, name, tolerance=1e-10):
    """Verify that a matrix is symmetric and report any asymmetry."""
    is_symmetric = np.allclose(matrix, matrix.T, atol=tolerance)
    max_asymmetry = np.max(np.abs(matrix - matrix.T))

    if is_symmetric:
        print(f"✓ {name}: Verified symmetric (max asymmetry: {max_asymmetry:.2e})")
    else:
        print(f"✗ {name}: NOT symmetric (max asymmetry: {max_asymmetry:.2e})")

    return is_symmetric


# Dictionary for easy access, same interface as losses.py
SYMMETRIC_METHODS = {
    'Euclidean': euclidean_distance_matrix,
    'CosineSimilarity': cosine_similarity_matrix,
    'JensenShannon': jensen_shannon_divergence_matrix,
    'Bhattacharyya': bhattacharyya_distance_matrix,
    'Hellinger': hellinger_distance_matrix,
    'Wasserstein': wasserstein_distance_matrix,
    'MMD': mmd_matrix,
}


if __name__ == '__main__':
    """Demo: show that all symmetric methods return identical scores for (A,B) and (B,A)."""
    np.random.seed(42)

    # Generate small sample
    latents = np.random.randn(20, 8)

    print("=" * 80)
    print("SYMMETRY VERIFICATION: Computing all symmetric methods on sample data")
    print("=" * 80)

    for method_name, method_fn in SYMMETRIC_METHODS.items():
        print(f"\n{method_name}:")
        matrix = method_fn(latents)
        verify_symmetry(matrix, method_name)

        # Show specific example
        i, j = 0, 1
        print(f"  matrix[{i},{j}] = {matrix[i,j]:.6f}")
        print(f"  matrix[{j},{i}] = {matrix[j,i]:.6f}")
        print(f"  Difference: {abs(matrix[i,j] - matrix[j,i]):.2e}")

    print("\n" + "=" * 80)
    print("CONCLUSION:")
    print("=" * 80)
    print("All symmetric methods return f(A, B) = f(B, A) exactly.")
    print("Therefore, they CANNOT be used to predict directional relations")
    print("(stronger vs. weaker) -- the score is identical regardless of order.")
    print("=" * 80)
