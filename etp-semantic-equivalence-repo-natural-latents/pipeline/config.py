"""Run configuration: one object shared by every method."""
import os
import sys
from dataclasses import dataclass, field, asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, 'src')
DATA_DIR = os.path.join(ROOT, 'data')
RESULTS_DIR = os.path.join(ROOT, 'results')

# the core algorithm modules (embeddings, resampling, losses, magma_fingerprints, ...)
for _p in (SRC_DIR, DATA_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@dataclass
class Config:
    # data
    sample_size: int = 1200            # equations sampled (all 19 representations present)
    pair_sample_size: int = 15000      # ordered pairs (unordered pairs x both directions)
    data_seed: int = 42

    # evaluation
    split_seeds: tuple = (42, 7, 123, 99, 256)
    test_frac: float = 0.3             # fraction of EQUATIONS held out per split

    # the ONE base classifier used by every learned method: 'hgb' or 'rf'
    classifier: str = 'hgb'
    hgb_params: dict = field(default_factory=lambda: dict(
        max_iter=300, learning_rate=0.05, class_weight='balanced', random_state=42))
    rf_params: dict = field(default_factory=lambda: dict(
        n_estimators=150, max_depth=8, min_samples_leaf=10, class_weight='balanced', random_state=42))
    n_jobs: int = 4                    # parallel worker processes (one per split)

    # embeddings / Natural Latents
    max_features: int = 500
    n_components: int = 8
    ridge_alpha: float = 1.0

    # structural / semantic
    wl_rounds: int = 3
    wl_min_count: int = 10
    exhaustive_size3_magmas: bool = True

    # output
    results_dir: str = RESULTS_DIR
    save_confusion_pngs: bool = True

    def as_dict(self):
        return asdict(self)
