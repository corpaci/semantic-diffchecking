"""
embeddings.py -- Two embedding schemes, both testable head-to-head.

1. GENERIC: character n-gram TF-IDF, same scheme across all 5 representations.
   This is what produced the ~46-47% accuracy result referenced throughout
   this project. Retained here unchanged as the baseline to compare against.

2. DOMAIN-SPECIFIC: a different, format-appropriate tokenizer per
   representation -- Lean gets its own keyword/symbol tokenizer, Python gets
   real syntactic tokenization (via Python's own `tokenize` module), LaTeX
   gets command-level tokenization, natural language gets word-level
   tokenization. The hypothesis: respecting each format's actual grammar
   should capture more real structure than one generic scheme applied
   blindly to all five.
"""
import re
import io
import tokenize as pytokenize
from sklearn.feature_extraction.text import TfidfVectorizer


# ---------------------------------------------------------------------------
# 1. GENERIC scheme -- char n-grams, same for every view
# ---------------------------------------------------------------------------
def make_generic_embedder(char_ngrams=(2, 4), max_features=800):
    fitted = {}
    def embed(texts, fit_key=None):
        key = fit_key or 'default'
        if key not in fitted:
            fitted[key] = TfidfVectorizer(analyzer='char', ngram_range=char_ngrams,
                                            max_features=max_features).fit(texts)
        return fitted[key].transform(texts).toarray()
    return embed


# ---------------------------------------------------------------------------
# 2. DOMAIN-SPECIFIC scheme -- a real tokenizer per representation type
# ---------------------------------------------------------------------------
def tokenize_lean(text):
    """Lean-aware: keep keywords, symbols (forall, magma-op diamond, etc.)
    and identifiers as separate tokens, rather than raw characters."""
    return re.findall(r'\\forall|\u2200|\u25c7|[A-Za-z_][A-Za-z0-9_]*|[=():\[\]]', text)


def tokenize_latex(text):
    """LaTeX-aware: backslash-commands as whole tokens, plus identifiers/symbols."""
    return re.findall(r'\\[a-zA-Z]+|[A-Za-z]+|[={}()\\]', text)


def tokenize_python(text):
    """Real Python syntactic tokens (NAME, OP, NUMBER, ...) via the stdlib
    tokenizer -- not just characters or words, actual code structure."""
    try:
        tokens = []
        for tok in pytokenize.generate_tokens(io.StringIO(text).readline):
            if tok.string.strip():
                tokens.append(tok.string)
        return tokens
    except Exception:
        return re.findall(r'\w+|[^\w\s]', text)   # fallback if tokenize chokes


def tokenize_words(text):
    """Word-level for natural language -- the appropriate granularity for prose."""
    return re.findall(r"[A-Za-z']+", text.lower())


TOKENIZERS = {
    'lean': tokenize_lean,
    'latex': tokenize_latex,
    'py_lambda': tokenize_python,
    'py_cayley_table': tokenize_python,
    'natural_language': tokenize_words,
}


def make_domain_specific_embedder(max_features=800):
    """Returns an embed(texts, fit_key=view_name) function that picks the
    right tokenizer based on fit_key (the view name)."""
    fitted = {}
    def embed(texts, fit_key=None):
        key = fit_key or 'default'
        tokenizer = TOKENIZERS.get(key, tokenize_words)
        if key not in fitted:
            fitted[key] = TfidfVectorizer(analyzer='word', tokenizer=tokenizer,
                                            token_pattern=None, max_features=max_features,
                                            lowercase=False).fit(texts)
        return fitted[key].transform(texts).toarray()
    return embed


if __name__ == '__main__':
    lean_sample = "example (G : Type u) [Magma G] : Prop := \u2200 x y : G, x \u25c7 y = y \u25c7 x"
    python_sample = "def law(table):\n    n = len(table)\n    return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))"
    print("Lean tokens:", tokenize_lean(lean_sample)[:10])
    print("Python tokens:", tokenize_python(python_sample)[:10])
