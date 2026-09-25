"""TF-IDF matrices per representation, for the three embedding schemes.

  generic  -- character 2-4-gram TF-IDF, identical for every view (src/embeddings.py)
  family   -- one tokenizer per representation FAMILY (src/embeddings_enhanced.py)
  repr     -- one parser per REPRESENTATION (src/embeddings_repr_specific.py)

These are fitted on all sampled equations (unsupervised, no labels involved),
exactly like the notebooks.
"""
import warnings

from .data import ALL_VIEWS

SCHEMES = {'generic': 'Generic char n-gram', 'family': 'Family-specific', 'repr': 'Representation-specific'}


def _make_embed(scheme, max_features):
    if scheme == 'generic':
        from embeddings import make_generic_embedder
        return make_generic_embedder(char_ngrams=(2, 4), max_features=max_features)
    if scheme == 'family':
        from embeddings_enhanced import make_enhanced_domain_embedder
        emb = make_enhanced_domain_embedder(char_ngrams=(2, 4), word_ngrams=(1, 2), max_features=max_features)
        return lambda texts, fit_key=None: emb.fit_transform(texts, fit_key)
    if scheme == 'repr':
        from embeddings_repr_specific import make_representation_specific_embedder
        return make_representation_specific_embedder(max_features=max_features)
    raise ValueError(scheme)


def tfidf_views(ctx, scheme):
    """{view: (n_equations, n_terms) dense TF-IDF matrix} for one scheme (cached)."""
    def build():
        embed = _make_embed(scheme, ctx.cfg.max_features)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return {v: embed(ctx.texts[v], fit_key=v) for v in ALL_VIEWS}
    return ctx.cached(f'tfidf[{scheme}]', build)
