"""Synthetic performance data for dry-run published posts.

Numbers are derived deterministically from the post id, so a given post always
reports the same trajectory, and they grow with post age on a saturating curve —
the shape real social engagement actually follows. Channel benchmarks keep the
relative ordering plausible (LinkedIn: fewer impressions, higher engagement
rate; TikTok: the reverse).
"""
import math
import random

from ..models import PostMetric, db, utcnow

# (impressions per follower-ish base, baseline engagement rate)
CHANNEL_BENCHMARKS = {
    'x': (2400, 0.012),
    'linkedin': (1400, 0.045),
    'instagram': (1800, 0.031),
    'facebook': (1100, 0.008),
    'tiktok': (5200, 0.052),
    'threads': (900, 0.022),
}

# Most engagement lands within the first day or two; the curve saturates after that.
HALF_LIFE_HOURS = 26.0
ANGLE_LIFT = {'question': 1.25, 'contrarian': 1.2, 'tip': 1.1, 'insight': 1.0, 'news': 0.9}


def _maturity(hours: float) -> float:
    return 1 - math.exp(-max(hours, 0.0) / HALF_LIFE_HOURS)


def synthesize(post, now=None) -> dict:
    now = now or utcnow()
    if not post.published_at:
        return {}

    rng = random.Random(f'metric:{post.id}:{post.channel}')
    base_impressions, base_rate = CHANNEL_BENCHMARKS.get(post.channel, (1200, 0.02))

    hours = (now - post.published_at).total_seconds() / 3600.0
    maturity = _maturity(hours)

    # Per-post variance: most posts land near the benchmark, a few break out.
    quality = rng.lognormvariate(0, 0.55)
    quality *= ANGLE_LIFT.get(post.angle, 1.0)
    if len(post.hashtag_list) > 0:
        quality *= 1.05

    impressions = int(base_impressions * quality * maturity)
    rate = max(0.001, min(0.25, base_rate * rng.uniform(0.6, 1.5)))
    engagements = int(impressions * rate)

    # Split engagements across interaction types with channel-agnostic ratios.
    likes = int(engagements * rng.uniform(0.55, 0.72))
    comments = int(engagements * rng.uniform(0.05, 0.14))
    shares = int(engagements * rng.uniform(0.04, 0.12))
    clicks = max(0, engagements - likes - comments - shares)

    return {
        'impressions': impressions,
        'likes': likes,
        'comments': comments,
        'shares': shares,
        'clicks': clicks,
    }


def refresh(post, now=None) -> PostMetric:
    """Recompute and store the latest metric snapshot for a published post."""
    values = synthesize(post, now)
    if not values:
        return None
    metric = PostMetric(post_id=post.id, captured_at=now or utcnow(), **values)
    db.session.add(metric)
    return metric
