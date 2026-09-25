"""Method registry: every module contributes a list of labelled methods."""
from . import advanced, natural_latents, semantic, structural, symmetric, thresholds

MODULES = {
    'symmetric': symmetric,
    'natural_latents': natural_latents,
    'advanced': advanced,
    'structural': structural,
    'thresholds': thresholds,
    'semantic': semantic,
}


def all_methods(cfg, modules=None):
    out = []
    for name, mod in MODULES.items():
        if modules is None or name in modules:
            out.extend(mod.get_methods(cfg))
    return out
