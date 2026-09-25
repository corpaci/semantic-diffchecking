"""The single base classifier shared by every learned method."""
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier


def make_classifier(cfg, n_jobs=None):
    if cfg.classifier == 'hgb':
        return HistGradientBoostingClassifier(**cfg.hgb_params)
    if cfg.classifier == 'rf':
        return RandomForestClassifier(n_jobs=n_jobs or cfg.n_jobs, **cfg.rf_params)
    raise ValueError(f"unknown classifier {cfg.classifier!r} (use 'hgb' or 'rf')")


def describe_classifier(cfg):
    params = cfg.hgb_params if cfg.classifier == 'hgb' else cfg.rf_params
    name = 'HistGradientBoostingClassifier' if cfg.classifier == 'hgb' else 'RandomForestClassifier'
    return f"{name}({', '.join(f'{k}={v}' for k, v in params.items())})"
