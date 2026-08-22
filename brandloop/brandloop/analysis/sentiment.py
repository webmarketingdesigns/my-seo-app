"""Lexicon sentiment scoring.

A deliberately dependency-free VADER-style scorer: a valence lexicon, negation
flipping, intensifier scaling, and punctuation/caps boosting. It is not as good
as a trained classifier, but it runs anywhere with no model download and its
decisions are inspectable, which matters when a human is auditing why a mention
was flagged negative.
"""
import math
import re

POSITIVE = {
    'amazing': 3.0, 'awesome': 3.0, 'excellent': 3.0, 'outstanding': 3.0, 'fantastic': 3.0,
    'brilliant': 2.8, 'love': 2.8, 'loved': 2.6, 'loves': 2.6, 'perfect': 2.8, 'superb': 2.8,
    'delighted': 2.6, 'impressed': 2.4, 'impressive': 2.4, 'great': 2.2, 'wonderful': 2.6,
    'best': 2.4, 'better': 1.4, 'good': 1.8, 'nice': 1.6, 'solid': 1.4, 'helpful': 1.8,
    'useful': 1.6, 'reliable': 1.8, 'fast': 1.2, 'smooth': 1.6, 'easy': 1.4, 'intuitive': 1.8,
    'recommend': 2.2, 'recommended': 2.2, 'happy': 2.2, 'pleased': 2.0, 'satisfied': 2.0,
    'win': 1.8, 'wins': 1.8, 'winner': 2.0, 'growth': 1.4, 'improved': 1.8, 'improvement': 1.6,
    'thanks': 1.6, 'thank': 1.6, 'grateful': 2.0, 'favorite': 2.2, 'favourite': 2.2,
    'worth': 1.4, 'clean': 1.2, 'polished': 1.8, 'seamless': 2.0, 'powerful': 1.8,
    'innovative': 2.0, 'game-changer': 2.6, 'gamechanger': 2.6, 'flawless': 2.8,
    'responsive': 1.6, 'supportive': 1.8, 'stellar': 2.6, 'praise': 2.0, 'success': 2.0,
    'successful': 2.0, 'efficient': 1.8, 'affordable': 1.6, 'value': 1.2, 'quality': 1.4,
}

NEGATIVE = {
    'terrible': -3.0, 'awful': -3.0, 'horrible': -3.0, 'worst': -3.0, 'garbage': -2.8,
    'useless': -2.6, 'broken': -2.4, 'bug': -1.6, 'bugs': -1.6, 'buggy': -2.2, 'crash': -2.4,
    'crashes': -2.4, 'crashed': -2.4, 'fail': -2.2, 'failed': -2.2, 'failure': -2.4,
    'hate': -2.8, 'hated': -2.6, 'bad': -2.0, 'poor': -2.0, 'worse': -1.8, 'slow': -1.6,
    'expensive': -1.4, 'overpriced': -2.2, 'disappointed': -2.4, 'disappointing': -2.4,
    'frustrating': -2.4, 'frustrated': -2.2, 'annoying': -2.0, 'confusing': -1.8,
    'complicated': -1.4, 'difficult': -1.4, 'hard': -1.0, 'issue': -1.2, 'issues': -1.4,
    'problem': -1.6, 'problems': -1.8, 'outage': -2.6, 'downtime': -2.4,
    'unreliable': -2.4, 'unusable': -2.8, 'scam': -3.0, 'fraud': -3.0, 'misleading': -2.2,
    'refund': -1.6, 'cancel': -1.6, 'cancelled': -1.6, 'canceling': -1.6, 'churn': -1.8,
    'complaint': -2.0, 'complaints': -2.0, 'ignored': -2.0, 'lacking': -1.6, 'missing': -1.2,
    'regret': -2.4, 'waste': -2.4, 'wasted': -2.4, 'clunky': -2.0, 'laggy': -2.0,
    'error': -1.6, 'errors': -1.8, 'blocked': -1.4, 'delay': -1.4, 'delayed': -1.4,
}

NEGATIONS = {
    "not", "no", "never", "none", "cannot", "cant", "can't", "won't", "wont", "isn't", "isnt",
    "aren't", "arent", "doesn't", "doesnt", "didn't", "didnt", "wasn't", "wasnt", "wouldn't",
    "wouldnt", "shouldn't", "shouldnt", "hardly", "barely", "without", "lack", "lacks",
}

INTENSIFIERS = {
    'very': 0.35, 'really': 0.3, 'extremely': 0.55, 'incredibly': 0.5, 'so': 0.25,
    'absolutely': 0.5, 'totally': 0.35, 'completely': 0.4, 'super': 0.35, 'insanely': 0.5,
    'quite': 0.15, 'pretty': 0.15, 'somewhat': -0.2, 'slightly': -0.3, 'kind': -0.15,
    'barely': -0.4, 'hugely': 0.45, 'massively': 0.45, 'seriously': 0.3,
}

EMOJI = {
    '🔥': 1.8, '❤️': 2.2, '😍': 2.4, '👏': 1.8, '🚀': 1.8, '💯': 2.0, '🙌': 1.8, '😊': 1.6,
    '👍': 1.6, '😡': -2.4, '😞': -2.0, '👎': -1.8, '💀': -1.2, '🤬': -2.8, '😤': -1.8, '🙄': -1.4,
}

LEXICON = {**POSITIVE, **NEGATIVE}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")

NEGATION_WINDOW = 3   # tokens before a term that a negation can flip
INTENSIFIER_WINDOW = 2

# Positive words outnumber negative ones in everyday marketing copy, so the
# label thresholds are asymmetric: it takes less negativity to earn a flag.
POSITIVE_THRESHOLD = 0.15
NEGATIVE_THRESHOLD = -0.10


def _tokenize(text: str):
    return [t.lower() for t in _TOKEN_RE.findall(text or '')]


def score_text(text: str) -> float:
    """Return a compound sentiment score in [-1.0, 1.0]."""
    if not text:
        return 0.0

    tokens = _tokenize(text)
    raw = 0.0
    hits = 0

    for i, token in enumerate(tokens):
        valence = LEXICON.get(token)
        if valence is None:
            continue
        hits += 1

        # Intensifiers immediately preceding the term scale its magnitude.
        for step in range(1, INTENSIFIER_WINDOW + 1):
            j = i - step
            if j < 0:
                break
            boost = INTENSIFIERS.get(tokens[j])
            if boost is not None:
                valence *= 1 + (boost / step)

        # A negation anywhere in the short window before the term flips and damps it.
        window = tokens[max(0, i - NEGATION_WINDOW):i]
        if any(w in NEGATIONS for w in window):
            valence *= -0.74

        raw += valence

    for emoji, valence in EMOJI.items():
        count = (text or '').count(emoji)
        if count:
            hits += count
            raw += valence * min(count, 3)

    if not hits:
        return 0.0

    # Emphasis: shouting and exclamation amplify whatever direction we found.
    letters = [c for c in text if c.isalpha()]
    if letters:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio > 0.6 and len(letters) > 12:
            raw *= 1.2
    raw += math.copysign(min(text.count('!'), 3) * 0.25, raw)

    # Normalise to (-1, 1); the divisor damps long texts that simply have more words.
    return max(-1.0, min(1.0, raw / math.sqrt(raw * raw + 15)))


def label_for(score: float) -> str:
    if score >= POSITIVE_THRESHOLD:
        return 'positive'
    if score <= NEGATIVE_THRESHOLD:
        return 'negative'
    return 'neutral'


def analyse(text: str) -> dict:
    score = score_text(text)
    return {'score': score, 'label': label_for(score)}
