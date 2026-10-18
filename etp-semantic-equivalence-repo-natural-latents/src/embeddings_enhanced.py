"""Enhanced domain-specific embeddings for all 19 representation types.

This module provides specialized embedding strategies for different representation families:
- Formal notations (lean, tptp, smtlib, latex)
- Programming representations (py_lambda, py_cayley_table, ssa)
- Structural encodings (rpn, polish, slots, json_ast, ascii_tree, graphviz)
- Natural language (natural_language, word_problem, text, text2)
- Confusable variants (confusable_vars)
"""

import re
from typing import Dict, List, Callable
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
import numpy as np


# Representation families for grouped processing
REPRESENTATION_FAMILIES = {
    'formal': ['lean', 'latex', 'tptp', 'smtlib', 'formal'],
    'code': ['py_lambda', 'py_cayley_table', 'ssa'],
    'structural': ['rpn', 'polish', 'slots', 'json_ast', 'ascii_tree', 'graphviz'],
    'natural': ['natural_language', 'word_problem', 'text', 'text2'],
    'confusable': ['confusable_vars']
}

# Get family for a representation
REP_TO_FAMILY = {}
for family, reps in REPRESENTATION_FAMILIES.items():
    for rep in reps:
        REP_TO_FAMILY[rep] = family


def tokenize_formal(text: str) -> List[str]:
    """Tokenizer for formal mathematical notations (lean, latex, tptp, smtlib)."""
    # Preserve mathematical operators and quantifiers
    tokens = []

    # Split on whitespace but preserve special symbols
    parts = re.findall(r'\w+|[∀∃∧∨→↔¬=≠<>≤≥◇⊕⊗∘•⋆+\-*/()[\]{},:;.]', text)

    for part in parts:
        # Further split camelCase and snake_case
        if part.isalnum():
            # Split camelCase: "forAll" -> ["for", "All"]
            subparts = re.sub('([a-z])([A-Z])', r'\1 \2', part).split()
            # Split snake_case: "for_all" -> ["for", "all"]
            subparts = [sp.split('_') for sp in subparts]
            tokens.extend([s.lower() for sp in subparts for s in sp if s])
        else:
            tokens.append(part)

    return tokens


def tokenize_code(text: str) -> List[str]:
    """Tokenizer for code representations (Python, SSA)."""
    # Preserve keywords, operators, and identifiers
    tokens = []

    # Python/code keywords
    keywords = {'lambda', 'def', 'return', 'if', 'else', 'for', 'while', 'assert',
                'all', 'any', 'range', 'len', 'in', 'not', 'and', 'or'}

    # Split on whitespace and special chars, preserving operators
    parts = re.findall(r'\w+|[=!<>+\-*/()[\]{},.:;]', text)

    for part in parts:
        if part.lower() in keywords:
            tokens.append(part.lower())
        elif part.isalnum():
            # Split camelCase/snake_case like formal
            subparts = re.sub('([a-z])([A-Z])', r'\1 \2', part).split()
            subparts = [sp.split('_') for sp in subparts]
            tokens.extend([s.lower() for sp in subparts for s in sp if s])
        else:
            tokens.append(part)

    return tokens


def tokenize_structural(text: str) -> List[str]:
    """Tokenizer for structural encodings (RPN, Polish, slots, JSON, trees)."""
    # For RPN/Polish: preserve operator order
    # For slots: preserve position info
    # For JSON/trees: preserve structure markers

    tokens = []

    # Handle JSON-like structures
    if '{' in text or '[' in text:
        # Preserve structure tokens
        parts = re.findall(r'\w+|[{}[\],:"=()]', text)
        tokens.extend(parts)
    else:
        # For RPN/Polish/slots: split on whitespace
        parts = text.split()
        tokens.extend(parts)

    return tokens


def tokenize_natural(text: str) -> List[str]:
    """Tokenizer for natural language representations."""
    # Standard NLP tokenization
    # Remove punctuation, lowercase, split on whitespace
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    tokens = text.split()

    # Remove stopwords
    stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    tokens = [t for t in tokens if t not in stopwords]

    return tokens


class EnhancedDomainEmbedder:
    """Enhanced embedder with family-specific tokenization strategies."""

    def __init__(self,
                 char_ngrams=(2, 4),
                 word_ngrams=(1, 2),
                 max_features=500,
                 use_family_specific=True):
        """
        Args:
            char_ngrams: Character n-gram range for character-level features
            word_ngrams: Word n-gram range for token-level features
            max_features: Maximum features per vectorizer
            use_family_specific: Whether to use family-specific tokenization
        """
        self.char_ngrams = char_ngrams
        self.word_ngrams = word_ngrams
        self.max_features = max_features
        self.use_family_specific = use_family_specific

        # Family-specific tokenizers
        self.family_tokenizers = {
            'formal': tokenize_formal,
            'code': tokenize_code,
            'structural': tokenize_structural,
            'natural': tokenize_natural,
            'confusable': tokenize_formal,  # Treat like formal
        }

        # Will store vectorizers per representation
        self.vectorizers = {}

    def _get_tokenizer(self, representation: str) -> Callable:
        """Get appropriate tokenizer for a representation."""
        if not self.use_family_specific:
            return None  # Use default

        family = REP_TO_FAMILY.get(representation, 'structural')
        return self.family_tokenizers.get(family, None)

    def fit_transform(self, texts: List[str], representation: str) -> np.ndarray:
        """Fit vectorizer and transform texts for a specific representation.

        Args:
            texts: List of text strings for this representation
            representation: Name of the representation (e.g., 'lean', 'py_lambda')

        Returns:
            Feature matrix (n_samples, n_features)
        """
        tokenizer = self._get_tokenizer(representation)

        # Create char-level vectorizer
        char_vec = TfidfVectorizer(
            analyzer='char',
            ngram_range=self.char_ngrams,
            max_features=self.max_features // 2,
            lowercase=True
        )

        # Create word-level vectorizer
        word_vec = TfidfVectorizer(
            analyzer='word',
            ngram_range=self.word_ngrams,
            max_features=self.max_features // 2,
            lowercase=True,
            tokenizer=tokenizer
        )

        # Transform
        try:
            char_features = char_vec.fit_transform(texts).toarray()
        except:
            # Fallback if char n-grams fail
            char_features = np.zeros((len(texts), self.max_features // 2))

        try:
            word_features = word_vec.fit_transform(texts).toarray()
        except:
            # Fallback if word n-grams fail
            word_features = np.zeros((len(texts), self.max_features // 2))

        # Concatenate
        features = np.hstack([char_features, word_features])

        # Store vectorizers
        self.vectorizers[representation] = (char_vec, word_vec)

        return features

    def transform(self, texts: List[str], representation: str) -> np.ndarray:
        """Transform texts using fitted vectorizer.

        Args:
            texts: List of text strings
            representation: Name of the representation

        Returns:
            Feature matrix (n_samples, n_features)
        """
        if representation not in self.vectorizers:
            raise ValueError(f"Vectorizer not fitted for {representation}")

        char_vec, word_vec = self.vectorizers[representation]

        try:
            char_features = char_vec.transform(texts).toarray()
        except:
            char_features = np.zeros((len(texts), self.max_features // 2))

        try:
            word_features = word_vec.transform(texts).toarray()
        except:
            word_features = np.zeros((len(texts), self.max_features // 2))

        features = np.hstack([char_features, word_features])
        return features


def make_enhanced_domain_embedder(char_ngrams=(2, 4),
                                   word_ngrams=(1, 2),
                                   max_features=500,
                                   use_family_specific=True):
    """Factory function to create enhanced domain-specific embedder.

    Args:
        char_ngrams: Character n-gram range
        word_ngrams: Word n-gram range
        max_features: Max features per vectorizer
        use_family_specific: Use family-specific tokenization

    Returns:
        EnhancedDomainEmbedder instance
    """
    return EnhancedDomainEmbedder(
        char_ngrams=char_ngrams,
        word_ngrams=word_ngrams,
        max_features=max_features,
        use_family_specific=use_family_specific
    )


def get_all_representations():
    """Get list of all 19 representations."""
    return [
        'lean', 'latex', 'py_lambda', 'py_cayley_table', 'natural_language',
        'formal', 'ssa', 'rpn', 'polish', 'slots', 'json_ast',
        'ascii_tree', 'graphviz', 'tptp', 'smtlib', 'text', 'text2',
        'word_problem', 'confusable_vars'
    ]


def get_representation_families():
    """Get representation families for grouped analysis."""
    return REPRESENTATION_FAMILIES
