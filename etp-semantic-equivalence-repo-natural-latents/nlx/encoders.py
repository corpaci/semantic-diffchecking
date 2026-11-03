"""A CHANNEL is one notation read through one encoder, named 'view:encoder' (e.g. 'lean:tfidf_word').
Every encoder is unsupervised (fitted on the texts of all sampled equations, no labels), exactly like the repo's TF-IDF,
and returns a dense (n_equations, d) float matrix.  Add your own with @register."""
import re
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from pipeline.utils.embeddings import tfidf_views

ENCODERS = {}
TOK = re.compile(r'[A-Za-z_]+|\d+|[^\sA-Za-z_\d]')


def register(name, desc, views=None):
    def deco(fn):
        ENCODERS[name] = dict(fn=fn, desc=desc, views=views)
        return fn
    return deco


def applies(enc, view):
    v = ENCODERS[enc]['views']
    return v is None or view in v


@register('tfidf_repr', 'one tokenizer per notation (the repo default)')
def _repr(ctx, view):
    return tfidf_views(ctx, 'repr')[view]


@register('tfidf_generic', 'character 2-4-gram TF-IDF, same for every notation')
def _generic(ctx, view):
    return tfidf_views(ctx, 'generic')[view]


@register('tfidf_family', 'one tokenizer per notation family')
def _family(ctx, view):
    return tfidf_views(ctx, 'family')[view]


@register('tfidf_word', 'word / symbol 1-2-gram TF-IDF (good for prose and token streams)')
def _word(ctx, view):
    v = TfidfVectorizer(tokenizer=TOK.findall, token_pattern=None, lowercase=False, ngram_range=(1, 2),
                        max_features=ctx.cfg.max_features, sublinear_tf=True)
    return v.fit_transform(ctx.texts[view]).toarray().astype(np.float32)


@register('lsa64', 'character TF-IDF reduced to 64 dimensions (a small dense embedding)')
def _lsa(ctx, view):
    X = tfidf_views(ctx, 'generic')[view]
    Z = TruncatedSVD(min(64, X.shape[1] - 1), random_state=0).fit_transform(X)
    return (Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)).astype(np.float32)


@register('wl_formal', 'Weisfeiler-Lehman subtree counts of the parsed equation (renaming-invariant)', views=['formal'])
def _wl(ctx, view):
    from wl_features import WLFeaturizer
    W = np.asarray(WLFeaturizer(h=3, min_count=3).fit(ctx.formal).transform(ctx.formal), dtype=np.float32)
    W = np.log1p(W)
    if W.shape[1] > 128:
        W = TruncatedSVD(128, random_state=0).fit_transform(W).astype(np.float32)
    return W


@register('inv_formal', '13 structural invariants of the equation tree (size, depth, variables, ...)', views=['formal'])
def _inv(ctx, view):
    import magma_fingerprints as mf
    G = np.stack([mf.structural_invariants(f) for f in ctx.formal]).astype(np.float32)
    return (G - G.mean(0)) / (G.std(0) + 1e-6)


def neural(model_name):
    """Optional: sentence-transformers model, e.g. 'st:all-MiniLM-L6-v2'.  Needs `pip install sentence-transformers` and
    internet access for the first download.  Not available in every environment."""
    def fn(ctx, view):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError('encoder needs sentence-transformers (pip install sentence-transformers): %s' % e)
        m = SentenceTransformer(model_name)
        return np.asarray(m.encode(ctx.texts[view], batch_size=64, normalize_embeddings=True), dtype=np.float32)
    return fn


def get_encoder(name):
    if name.startswith('st:') and name not in ENCODERS:
        ENCODERS[name] = dict(fn=neural(name[3:]), desc='sentence-transformers model ' + name[3:], views=None)
    return ENCODERS[name]


def channel(view, enc):
    return f'{view}:{enc}'


def split_channel(ch):
    v, e = ch.split(':', 1)
    return v, e


def get_channel(ctx, ch):
    """Dense matrix (n_equations, d) of one channel, cached in the context."""
    view, enc = split_channel(ch)
    return ctx.cached(f'nlx[{ch}]', lambda: np.asarray(get_encoder(enc)['fn'](ctx, view), dtype=np.float32))
