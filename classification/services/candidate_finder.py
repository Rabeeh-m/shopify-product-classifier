import re
from collections import namedtuple

from django.conf import settings

# EXTENSION POINT: This module implements keyword/text-overlap scoring for
# candidate narrowing. The public API (CandidateResult, find_candidates) can
# be preserved exactly when swapping to embedding-based similarity search.
# A future implementation would replace _score_category with a vector
# similarity function while keeping the same function signature and return
# type, requiring no changes to callers.

CandidateResult = namedtuple("CandidateResult", ["category", "score"])

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "it",
        "as",
        "be",
        "was",
        "are",
        "this",
        "that",
        "not",
        "no",
        "so",
        "if",
        "my",
        "your",
        "our",
        "its",
        "their",
        "can",
        "will",
        "do",
        "has",
        "have",
        "had",
        "been",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _simple_stem(word):
    """Minimal English stemmer — strips common plural/inflection suffixes.

    Not a real stemmer. Just enough so "sofas" matches "sofa",
    "shirts" matches "shirt", etc.
    """
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") and len(word) > 4:
        return word[:-2]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _tokenize(text):
    """Lowercase, stem, strip punctuation, split into word tokens."""
    if not text:
        return set()
    return {
        _simple_stem(t.lower())
        for t in _TOKEN_RE.findall(text)
        if len(t) >= 2 and t.lower() not in _STOP_WORDS
    }


def _build_product_tokens(product):
    """Extract meaningful tokens from a product's text fields."""
    parts = [
        product.title or "",
        product.description or "",
        product.product_type or "",
    ]
    return _tokenize(" ".join(parts))


def _score_category(product_tokens, category):
    """Score a single category against a set of product tokens.

    Scoring weights:
      - Match in category name: 3 points (specific, high signal)
      - Match in full_path (non-name portion): 1 point (contextual)
      - Bonus for matching in both: 0.5 points
    """
    if not product_tokens:
        return 0.0

    name_tokens = _tokenize(category.name)
    path_tokens = _tokenize(category.full_path) - name_tokens

    score = 0.0
    for token in product_tokens:
        in_name = token in name_tokens
        in_path = token in path_tokens
        if in_name:
            score += 3.0
        if in_path:
            score += 1.0
        if in_name and in_path:
            score += 0.5

    return score


def find_candidates(product, categories=None, limit=None):
    """Return the top N category candidates for a product.

    Args:
        product: A Product instance (or any object with title, description,
            and product_type string attributes).
        categories: Optional iterable of Category objects. If None, the
            full taxonomy is loaded from cache (one DB query per TTL expiry
            rather than per product).  Pass a pre-loaded list to skip even
            the cache lookup.
        limit: Max results. Defaults to settings.CLASSIFICATION_CANDIDATE_LIMIT.

    Returns:
        A list of CandidateResult namedtuples sorted by descending score.
        The list may be shorter than limit if fewer categories exist.
    """
    if limit is None:
        limit = settings.CLASSIFICATION_CANDIDATE_LIMIT

    if categories is None:
        from taxonomy.services.cache import get_all_categories

        categories = get_all_categories()

    product_tokens = _build_product_tokens(product)
    if not product_tokens:
        return []

    scored = []
    for cat in categories:
        s = _score_category(product_tokens, cat)
        if s > 0:
            scored.append(CandidateResult(category=cat, score=s))

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:limit]
