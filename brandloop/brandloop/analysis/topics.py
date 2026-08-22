"""Topic extraction and trend detection over a set of mentions.

Terms are scored by how much more often they appear in the recent window than
in the window before it, so a term that is merely common (the brand's own name,
say) does not dominate the trending list.
"""
import math
import re
from collections import Counter
from datetime import timedelta

STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'all', 'also', 'am', 'an', 'and', 'any', 'are',
    'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but',
    'by', 'can', 'could', 'did', 'do', 'does', 'doing', 'down', 'during', 'each', 'few', 'for',
    'from', 'further', 'get', 'got', 'had', 'has', 'have', 'having', 'he', 'her', 'here', 'hers',
    'him', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 'like',
    'me', 'more', 'most', 'my', 'no', 'nor', 'not', 'now', 'of', 'off', 'on', 'once', 'only',
    'or', 'other', 'our', 'ours', 'out', 'over', 'own', 'really', 'same', 'she', 'should', 'so',
    'some', 'such', 'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they',
    'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 'us', 'very', 'was', 'we',
    'were', 'what', 'when', 'where', 'which', 'while', 'who', 'whom', 'why', 'will', 'with',
    'would', 'you', 'your', 'yours', 'been', 'were', 'much', 'many', 'make', 'made', 'even',
    'still', 'back', 'want', 'need', 'know', 'think', 'see', 'way', 'new', 'one', 'two', 'via',
    'amp', 'http', 'https', 'com', 'www', 'said', 'says', 'first', 'last', 'next', 'day', 'days',
    'week', 'month', 'year', 'time', 'people', 'thing', 'things', 'lot', 'good', 'bad', 'best',
}

# Matches short words too. They can never be terms (see _keyword), but they
# must stay in the sequence: dropping "a" would make "behind a higher tier"
# produce the phantom phrase "behind higher".
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_SENTENCE_RE = re.compile(r'[.!?\n]+')
MIN_TERM_LEN = 3


def _sentences(text: str):
    return [s for s in _SENTENCE_RE.split(text or '') if s.strip()]


def _tokens(text: str):
    return [t.lower() for t in _TOKEN_RE.findall(text or '')]


def _keyword(token: str, ignore_set) -> bool:
    return len(token) >= MIN_TERM_LEN and token not in STOPWORDS and token not in ignore_set


def extract_terms(texts, top_n: int = 25, include_bigrams: bool = True, ignore=()) -> list:
    """Count meaningful unigrams and adjacent bigrams across `texts`.

    Bigrams are built from words that are genuinely adjacent in the source and
    within one sentence. Building them after stripping stopwords would glue
    together words that never touched ("pricing changes are terrible" would
    yield "changes terrible"), which reads as a phrase but means nothing.
    """
    ignore_set = {t.lower() for t in ignore}
    counts = Counter()

    for text in texts:
        seen_here = set()
        for sentence in _sentences(text):
            toks = _tokens(sentence)
            for tok in toks:
                if _keyword(tok, ignore_set) and tok not in seen_here:
                    seen_here.add(tok)
                    counts[tok] += 1
            if not include_bigrams:
                continue
            for a, b in zip(toks, toks[1:]):
                if not (_keyword(a, ignore_set) and _keyword(b, ignore_set)):
                    continue
                bigram = f'{a} {b}'
                if bigram in seen_here:
                    continue
                seen_here.add(bigram)
                counts[bigram] += 1

    # A bigram appearing once is noise from a single document.
    for term in [t for t, c in counts.items() if ' ' in t and c < 2]:
        del counts[term]

    return counts.most_common(top_n)


def _drop_absorbed(results: list) -> list:
    """Remove unigrams fully explained by a stronger phrase.

    If "influencer discovery" and "influencer" have the same count, the phrase
    is the real topic and the bare word is a duplicate of it.
    """
    phrases = [r for r in results if ' ' in r['term']]
    kept = []
    for row in results:
        if ' ' not in row['term'] and any(
            row['term'] in phrase['term'].split() and phrase['count'] >= row['count']
            for phrase in phrases
        ):
            continue
        kept.append(row)
    return kept


def trending_terms(mentions, now, window_hours: int = 168, top_n: int = 12, ignore=()) -> list:
    """Terms rising in the recent window versus the window before it.

    Returns dicts with the raw count, the prior count, and a momentum score that
    blends volume with relative lift so a term going 1 → 3 does not outrank one
    going 20 → 45.
    """
    cutoff = now - timedelta(hours=window_hours)
    prior_cutoff = cutoff - timedelta(hours=window_hours)

    recent, prior = [], []
    sentiment_by_term = {}

    for m in mentions:
        text = f'{m.title or ""} {m.content or ""}'
        if m.published_at >= cutoff:
            recent.append((text, m.sentiment_score or 0.0))
        elif m.published_at >= prior_cutoff:
            prior.append(text)

    recent_counts = dict(extract_terms([t for t, _ in recent], top_n=400, ignore=ignore))
    prior_counts = dict(extract_terms(prior, top_n=400, ignore=ignore))

    # Average sentiment of the mentions each surviving term appears in.
    for term in recent_counts:
        scores = [s for text, s in recent if term in text.lower()]
        if scores:
            sentiment_by_term[term] = sum(scores) / len(scores)

    results = []
    for term, count in recent_counts.items():
        if count < 2:
            continue
        before = prior_counts.get(term, 0)
        lift = (count - before) / (before + 1)
        # Phrases carry more meaning than the words they contain, so a bigram
        # outranks its own unigrams at equal volume.
        phrase_bonus = 1.25 if ' ' in term else 1.0
        momentum = lift * math.log1p(count) * phrase_bonus
        results.append({
            'term': term,
            'count': count,
            'prior_count': before,
            'lift': round(lift, 2),
            'momentum': round(momentum, 3),
            'sentiment': round(sentiment_by_term.get(term, 0.0), 3),
        })

    results.sort(key=lambda r: (r['momentum'], r['count']), reverse=True)
    return _drop_absorbed(results)[:top_n]
