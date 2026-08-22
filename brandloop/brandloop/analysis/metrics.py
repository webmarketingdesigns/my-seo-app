"""Aggregations that back the dashboard, insights and analytics pages."""
from collections import Counter, defaultdict
from datetime import timedelta

from ..models import Mention, Post, PostMetric, db


def _bucket_days(start, days: int):
    return [(start + timedelta(days=i)).date() for i in range(days)]


def volume_series(mentions, now, days: int = 14) -> dict:
    """Daily mention counts split by sentiment label."""
    start = now - timedelta(days=days - 1)
    buckets = _bucket_days(start, days)
    index = {d: i for i, d in enumerate(buckets)}

    series = {'positive': [0] * days, 'neutral': [0] * days, 'negative': [0] * days}
    for m in mentions:
        i = index.get(m.published_at.date())
        if i is None:
            continue
        series.setdefault(m.sentiment_label or 'neutral', [0] * days)[i] += 1

    return {
        'labels': [d.strftime('%b %d') for d in buckets],
        'positive': series['positive'],
        'neutral': series['neutral'],
        'negative': series['negative'],
        'total': [p + n + g for p, n, g in zip(series['positive'], series['neutral'], series['negative'])],
    }


def sentiment_series(mentions, now, days: int = 14) -> dict:
    """Daily mean sentiment, carrying the last known value through empty days."""
    start = now - timedelta(days=days - 1)
    buckets = _bucket_days(start, days)
    index = {d: i for i, d in enumerate(buckets)}

    sums = [0.0] * days
    counts = [0] * days
    for m in mentions:
        i = index.get(m.published_at.date())
        if i is None:
            continue
        sums[i] += m.sentiment_score or 0.0
        counts[i] += 1

    values, last = [], 0.0
    for s, c in zip(sums, counts):
        last = (s / c) if c else last
        values.append(round(last, 3))

    return {'labels': [d.strftime('%b %d') for d in buckets], 'values': values}


def share_of_voice(mentions) -> list:
    """Mention share for the brand versus each tracked competitor."""
    counts = Counter()
    reach = Counter()
    sentiment = defaultdict(list)

    for m in mentions:
        subject = m.subject or 'Brand'
        counts[subject] += 1
        reach[subject] += m.reach or 0
        sentiment[subject].append(m.sentiment_score or 0.0)

    total = sum(counts.values()) or 1
    rows = []
    for subject, count in counts.most_common():
        scores = sentiment[subject]
        rows.append({
            'subject': subject,
            'mentions': count,
            'share': round(count / total, 4),
            'reach': reach[subject],
            'sentiment': round(sum(scores) / len(scores), 3) if scores else 0.0,
        })
    return rows


def source_breakdown(mentions, limit: int = 10) -> list:
    """Where mentions come from, by outlet rather than by adapter type."""
    counts = Counter((m.source_label or m.source_kind, m.source_kind) for m in mentions)
    total = sum(counts.values()) or 1
    return [
        {'source': label, 'kind': kind, 'count': count, 'share': round(count / total, 4)}
        for (label, kind), count in counts.most_common(limit)
    ]


def _window_stats(mentions, start, end) -> dict:
    subset = [m for m in mentions if start <= m.published_at < end]
    if not subset:
        return {'count': 0, 'sentiment': 0.0, 'reach': 0, 'negative': 0}
    return {
        'count': len(subset),
        'sentiment': sum(m.sentiment_score or 0.0 for m in subset) / len(subset),
        'reach': sum(m.reach or 0 for m in subset),
        'negative': sum(1 for m in subset if m.sentiment_label == 'negative'),
    }


def _delta(current, prior) -> float:
    if not prior:
        return 1.0 if current else 0.0
    return (current - prior) / prior


def brand_dashboard(brand_id: int, now, days: int = 7) -> dict:
    """Headline KPIs comparing the last `days` against the `days` before them."""
    lookback = now - timedelta(days=days * 2)
    mentions = (
        Mention.query.filter(Mention.brand_id == brand_id, Mention.published_at >= lookback)
        .order_by(Mention.published_at.desc())
        .all()
    )

    mid = now - timedelta(days=days)
    current = _window_stats(mentions, mid, now + timedelta(days=1))
    prior = _window_stats(mentions, lookback, mid)

    published = (
        Post.query.filter(Post.brand_id == brand_id, Post.status == 'published',
                          Post.published_at >= mid)
        .all()
    )
    prior_published = (
        Post.query.filter(Post.brand_id == brand_id, Post.status == 'published',
                          Post.published_at >= lookback, Post.published_at < mid)
        .all()
    )

    def engagement(posts):
        total = 0
        impressions = 0
        for p in posts:
            metric = p.latest_metric
            if metric:
                total += metric.engagements
                impressions += metric.impressions or 0
        return total, impressions

    eng, impressions = engagement(published)
    prior_eng, _ = engagement(prior_published)

    pending = Post.query.filter(Post.brand_id == brand_id, Post.status == 'draft').count()
    scheduled = Post.query.filter(Post.brand_id == brand_id, Post.status == 'scheduled').count()

    return {
        'window_days': days,
        'mentions': {
            'value': current['count'],
            'delta': round(_delta(current['count'], prior['count']), 4),
        },
        'sentiment': {
            'value': round(current['sentiment'], 3),
            'delta': round(current['sentiment'] - prior['sentiment'], 3),
        },
        'reach': {
            'value': current['reach'],
            'delta': round(_delta(current['reach'], prior['reach']), 4),
        },
        'negative': {
            'value': current['negative'],
            'delta': round(_delta(current['negative'], prior['negative']), 4),
        },
        'engagements': {
            'value': eng,
            'delta': round(_delta(eng, prior_eng), 4),
        },
        'impressions': {'value': impressions},
        'posts_published': {'value': len(published)},
        'posts_pending': {'value': pending},
        'posts_scheduled': {'value': scheduled},
        'mentions_all': mentions,
    }


def channel_performance(brand_id: int) -> list:
    """Per-channel published volume and engagement, best channel first."""
    posts = Post.query.filter(Post.brand_id == brand_id, Post.status == 'published').all()
    grouped = defaultdict(lambda: {'posts': 0, 'impressions': 0, 'engagements': 0})

    for p in posts:
        metric = p.latest_metric
        row = grouped[p.channel]
        row['posts'] += 1
        if metric:
            row['impressions'] += metric.impressions or 0
            row['engagements'] += metric.engagements

    rows = []
    for channel, row in grouped.items():
        rate = (row['engagements'] / row['impressions']) if row['impressions'] else 0.0
        rows.append({'channel': channel, 'engagement_rate': round(rate, 4), **row})
    rows.sort(key=lambda r: r['engagement_rate'], reverse=True)
    return rows
