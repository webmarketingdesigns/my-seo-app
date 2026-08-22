"""First-run setup.

A brand-new database shows nothing, which makes the product impossible to judge.
On first boot we create one worked example — a brand, its query, real free
sources, seeded chatter and a back-dated posting history — so every screen has
something on it. It runs only when the brands table is empty.
"""
import random
from datetime import timedelta

from flask import current_app

from .analysis.alerts import evaluate_alerts
from .generate.composer import _template_posts, pick_topics
from .ingest.pipeline import run_seed
from .models import Brand, Keyword, Post, Source, db, utcnow
from .publish import dryrun, metrics

DEMO_BRAND = {
    'name': 'Northwind Analytics',
    'website': 'https://example.com',
    'description': 'Consumer intelligence for marketing teams — social listening, '
                   'sentiment and content automation in one place.',
}

DEMO_KEYWORDS = [
    ('Northwind Analytics', 'include'),
    ('Northwind', 'include'),
    ('social listening', 'include'),
    ('northwind turbine', 'exclude'),
    ('Brandwatch', 'competitor'),
    ('Sprout Social', 'competitor'),
]

# Free, key-less sources. They are created enabled but are only polled when a
# user (or cron) triggers ingestion, so first boot never blocks on the network.
DEMO_SOURCES = [
    ('hackernews', 'Hacker News — social listening', 'social listening'),
    ('reddit', 'Reddit — brand monitoring', 'social listening OR brand monitoring'),
    ('rss', 'Search Engine Land', 'https://searchengineland.com/feed'),
    ('rss', 'Google News — social listening', 
     'https://news.google.com/rss/search?q=%22social+listening%22&hl=en-US&gl=US&ceid=US:en'),
]

DEMO_VOICE = {
    'tone': 'clear and measured, speaks directly to the reader',
    'audience': 'marketing teams',
    'pillars': ['social listening', 'brand health', 'content strategy', 'competitive intelligence'],
    'summary': DEMO_BRAND['description'],
    'vocabulary': ['listening', 'sentiment', 'share of voice', 'brand health', 'reporting',
                   'competitive intelligence', 'content calendar'],
    'source': 'seed',
}

HISTORY_DAYS = 21
POSTS_PER_WEEK = 5


def _seed_posting_history(brand, now):
    """Back-date a few weeks of published posts so analytics has a baseline."""
    rng = random.Random(f'history:{brand.id}')
    topics = [t['term'] for t in pick_topics(brand, now, limit=8)] or ['social listening']
    channels = ['linkedin', 'x', 'instagram', 'facebook']

    created = 0
    for day_offset in range(HISTORY_DAYS, 0, -1):
        if rng.random() > POSTS_PER_WEEK / 7:
            continue
        published_at = (now - timedelta(days=day_offset)).replace(
            hour=rng.choice((9, 12, 15, 18)), minute=0, second=0, microsecond=0
        )
        topic = rng.choice(topics)
        channel = rng.choice(channels)
        draft = _template_posts(brand, brand.voice, topic, [channel], rng)[0]

        post = Post(
            brand_id=brand.id, channel=channel, body=draft['body'],
            hashtags=' '.join(draft['hashtags']), status='published', angle=draft['angle'],
            topic=topic, generator='template', scheduled_for=published_at,
            published_at=published_at, created_at=published_at - timedelta(days=1),
        )
        db.session.add(post)
        db.session.flush()  # need the id before the publisher can build a permalink
        post.external_url = dryrun.publish(post, brand, current_app.config)['external_url']
        metrics.refresh(post, now)
        created += 1

    db.session.commit()
    return created


def ensure_demo_brand():
    """Create the worked example if the database has no brands yet."""
    if Brand.query.first() is not None:
        return None

    now = utcnow()
    brand = Brand(**DEMO_BRAND)
    brand.voice = DEMO_VOICE
    db.session.add(brand)
    db.session.flush()

    for term, kind in DEMO_KEYWORDS:
        db.session.add(Keyword(brand_id=brand.id, term=term, kind=kind))
    for kind, label, config in DEMO_SOURCES:
        db.session.add(Source(brand_id=brand.id, kind=kind, label=label, config=config))
    db.session.commit()

    run_seed(brand, now, days=30, per_day=6)
    _seed_posting_history(brand, now)

    # Draft a small approval queue so the studio is not empty either.
    from .generate.composer import generate_drafts
    generate_drafts(brand, current_app.config, count=3, channels=['linkedin', 'x'], now=now)

    evaluate_alerts(brand, now)
    return brand
