"""Approval → schedule → publish → measure.

The scheduler has no background worker: `run_due` is idempotent and safe to call
from a request, a cron job, or the CLI. On a free Render plan a cron job hitting
POST /api/scheduler/run is enough; nothing here assumes a long-lived process.
"""
from datetime import timedelta

from .models import Post, db, utcnow
from .publish import PublishError, metrics, publisher_for

# When a post is approved without an explicit time, spread it across the next few
# days at hours that historically see engagement, rather than dumping everything now.
PREFERRED_HOURS = (9, 12, 15, 18)
METRIC_REFRESH_MINUTES = 60


def next_slot(brand_id: int, now, spacing_hours: int = 4):
    """Find the next free posting slot for a brand."""
    taken = {
        row[0].replace(minute=0, second=0, microsecond=0)
        for row in db.session.query(Post.scheduled_for)
        .filter(Post.brand_id == brand_id, Post.scheduled_for.isnot(None),
                Post.status.in_(('scheduled', 'published')))
        .all()
        if row[0]
    }

    candidate = now + timedelta(hours=1)
    for _ in range(14 * len(PREFERRED_HOURS)):
        hour = min((h for h in PREFERRED_HOURS if h >= candidate.hour), default=None)
        if hour is None:
            candidate = (candidate + timedelta(days=1)).replace(hour=PREFERRED_HOURS[0])
        else:
            candidate = candidate.replace(hour=hour, minute=0, second=0, microsecond=0)

        if candidate not in taken and candidate > now:
            return candidate
        candidate += timedelta(hours=spacing_hours)
    return now + timedelta(hours=1)


def approve(post, now=None, scheduled_for=None) -> Post:
    """Approve a draft and put it in the queue."""
    now = now or utcnow()
    post.status = 'scheduled'
    post.scheduled_for = scheduled_for or next_slot(post.brand_id, now)
    db.session.commit()
    return post


def reject(post) -> Post:
    post.status = 'rejected'
    post.scheduled_for = None
    db.session.commit()
    return post


def publish_now(post, brand, config, now=None) -> dict:
    """Publish a single post immediately and capture its first metric snapshot."""
    now = now or utcnow()
    try:
        result = publisher_for(post.channel)(post, brand, config)
    except PublishError as exc:
        return {'post_id': post.id, 'published': False, 'error': str(exc)}

    post.status = 'published'
    post.published_at = now
    post.external_url = result.get('external_url', '')
    metrics.refresh(post, now)
    db.session.commit()
    return {'post_id': post.id, 'published': True, 'url': post.external_url,
            'simulated': result.get('simulated', False)}


def run_due(brand, config, now=None) -> dict:
    """Publish everything whose scheduled time has arrived, then refresh metrics."""
    now = now or utcnow()

    due = Post.query.filter(
        Post.brand_id == brand.id,
        Post.status == 'scheduled',
        Post.scheduled_for.isnot(None),
        Post.scheduled_for <= now,
    ).all()

    results = [publish_now(post, brand, config, now) for post in due]
    refreshed = refresh_metrics(brand, now)

    return {
        'published': sum(1 for r in results if r['published']),
        'failed': [r for r in results if not r['published']],
        'metrics_refreshed': refreshed,
        'ran_at': now.isoformat(),
    }


def refresh_metrics(brand, now=None) -> int:
    """Re-snapshot published posts whose last reading is stale."""
    now = now or utcnow()
    cutoff = now - timedelta(minutes=METRIC_REFRESH_MINUTES)
    posts = Post.query.filter(Post.brand_id == brand.id, Post.status == 'published').all()

    refreshed = 0
    for post in posts:
        latest = post.latest_metric
        if latest is None or (latest.captured_at or now) <= cutoff:
            metrics.refresh(post, now)
            refreshed += 1

    if refreshed:
        db.session.commit()
    return refreshed
