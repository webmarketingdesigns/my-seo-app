"""Synthetic mention generator.

Free sources give real but thin coverage — a brand new workspace would show an
empty dashboard, which makes the product impossible to evaluate. The seeder
fills the last N days with plausible chatter so every chart, alert rule and
topic list has something to work on. Seeded mentions are tagged with
source_kind='seed' and can be cleared independently of real data.
"""
import random
from datetime import timedelta

from .base import raw_item, stable_id

TEMPLATES = {
    'positive': [
        'Switched to {brand} last month and the {feature} alone paid for it. Genuinely impressed.',
        'Shoutout to {brand} support — fixed my {feature} issue in under an hour. Excellent service.',
        '{brand} just shipped {feature} and it is seriously good. Best release this year.',
        'We compared {brand} and {competitor}. {brand} won on {feature}, easily. Highly recommended.',
        'Three months on {brand}: reporting time down 60%. The {feature} workflow is seamless.',
        'Honestly did not expect {brand} to handle {feature} this well. Very impressed with the quality.',
    ],
    'neutral': [
        '{brand} announced updates to {feature} this week. Rolling out to all plans by the end of the month.',
        'Anyone here using {brand} for {feature}? Trying to decide between them and {competitor}.',
        'Wrote up a comparison of {brand}, {competitor} and two others. Notes on {feature} in the thread.',
        'Question: does {brand} support {feature} on the starter tier, or is that enterprise only?',
        '{brand} published their quarterly numbers today. {feature} usage was the headline metric.',
        'Migrating from {competitor} to {brand} next quarter. Mostly for the {feature} coverage.',
    ],
    'negative': [
        '{brand} has been down twice this week. The {feature} outage cost us a full afternoon.',
        'Really disappointed with {brand}. {feature} is buggy and support has ignored my ticket for days.',
        'Cancelling our {brand} subscription. Overpriced for what you get and {feature} is unusable.',
        'Why is {brand} {feature} so slow? {competitor} does the same thing instantly. Frustrating.',
        '{brand} pricing changes are terrible for small teams. {feature} moved behind a higher tier.',
        'Third {feature} error today on {brand}. This is getting really annoying.',
    ],
}

FEATURES = [
    'sentiment scoring', 'the API', 'dashboard exports', 'alerting', 'the mobile app',
    'boolean queries', 'share of voice', 'the content calendar', 'influencer discovery',
    'historical data', 'onboarding', 'the Slack integration', 'reporting', 'billing',
]

SOURCE_POOL = [
    ('reddit', 'r/marketing', 400), ('reddit', 'r/SaaS', 300), ('reddit', 'r/socialmedia', 250),
    ('hackernews', 'Hacker News', 900), ('rss', 'TechCrunch', 12000), ('rss', 'The Verge', 9000),
    ('rss', 'Marketing Brew', 3000), ('rss', 'Search Engine Land', 2600), ('rss', 'Product Blog', 500),
]

AUTHORS = [
    'mkramer', 'jen_ops', 'growth_dave', 'sara.builds', 'the_pm_life', 'nordic_marketer',
    'anna_h', 'quietlaunch', 'b2b_becca', 'tomas_v', 'devrel_dan', 'lena.writes',
]

# Weekday chatter roughly doubles weekend chatter; the seeder mirrors that so
# volume charts do not look artificially flat.
WEEKDAY_WEIGHT = {0: 1.0, 1: 1.15, 2: 1.2, 3: 1.1, 4: 0.9, 5: 0.5, 6: 0.45}


def generate(brand_name: str, competitors, now, days: int = 30, per_day: int = 6,
             negative_share: float = 0.18, positive_share: float = 0.42, seed=None) -> list:
    """Build a list of raw items spanning the last `days` days."""
    rng = random.Random(seed if seed is not None else brand_name)
    competitors = list(competitors) or ['a competitor']
    items = []

    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        weight = WEEKDAY_WEIGHT.get(day.weekday(), 1.0)
        # A recency ramp: more chatter close to today, so trend lines have direction.
        recency = 1.0 + (0.5 * (days - day_offset) / days)
        count = max(0, int(round(rng.gauss(per_day * weight * recency, 1.4))))

        for _ in range(count):
            roll = rng.random()
            if roll < negative_share:
                tone = 'negative'
            elif roll < negative_share + positive_share:
                tone = 'positive'
            else:
                tone = 'neutral'

            kind, label, reach_base = rng.choice(SOURCE_POOL)
            competitor = rng.choice(competitors)
            # Roughly a fifth of chatter is about the competitor, not us.
            about_competitor = rng.random() < 0.2
            subject_name = competitor if about_competitor else brand_name

            text = rng.choice(TEMPLATES[tone]).format(
                brand=subject_name,
                competitor=brand_name if about_competitor else competitor,
                feature=rng.choice(FEATURES),
            )
            published = day.replace(
                hour=rng.randint(6, 22), minute=rng.randint(0, 59), second=rng.randint(0, 59),
                microsecond=0,
            )
            reach = int(reach_base * rng.uniform(0.4, 2.5))
            if rng.random() < 0.03:
                reach *= rng.randint(5, 12)  # the occasional post that takes off

            title = text.split('.')[0][:120]
            items.append(raw_item(
                external_id=stable_id('seed', brand_name, published.isoformat(), text[:60]),
                title=title,
                content=text,
                url=f'https://example.com/{kind}/{stable_id(text)[:10]}',
                author=rng.choice(AUTHORS),
                published_at=published,
                reach=reach,
                source_label=label,
                subject=subject_name,
            ))

    return items
