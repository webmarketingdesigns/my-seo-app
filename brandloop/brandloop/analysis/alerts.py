"""Derived signals worth interrupting a human for.

Every rule produces a stable fingerprint so a condition that persists across
several ingestion runs does not create a new alert each time.
"""
from datetime import timedelta

from ..models import Alert, Mention, db

VOLUME_SPIKE_RATIO = 2.0      # recent volume must double the prior window
VOLUME_SPIKE_FLOOR = 5        # ...and clear this many mentions, to ignore 1 → 3
NEGATIVE_SHARE_THRESHOLD = 0.35
NEGATIVE_FLOOR = 4
VIRAL_REACH_MULTIPLE = 4.0    # a single mention this far above the mean is viral


def _existing(brand_id: int, fingerprint: str, since) -> bool:
    return (
        Alert.query.filter(
            Alert.brand_id == brand_id,
            Alert.fingerprint == fingerprint,
            Alert.created_at >= since,
        ).first()
        is not None
    )


def evaluate_alerts(brand, now, window_hours: int = 24) -> list:
    """Run every rule and persist any newly firing alert. Returns new alerts."""
    cutoff = now - timedelta(hours=window_hours)
    prior_cutoff = cutoff - timedelta(hours=window_hours)
    dedupe_since = now - timedelta(hours=window_hours)

    recent = Mention.query.filter(
        Mention.brand_id == brand.id,
        Mention.published_at >= cutoff,
        Mention.is_competitor.is_(False),
    ).all()
    prior_count = Mention.query.filter(
        Mention.brand_id == brand.id,
        Mention.published_at >= prior_cutoff,
        Mention.published_at < cutoff,
        Mention.is_competitor.is_(False),
    ).count()

    created = []
    day_key = now.strftime('%Y-%m-%d')

    # 1. Volume spike
    if len(recent) >= VOLUME_SPIKE_FLOOR and len(recent) >= prior_count * VOLUME_SPIKE_RATIO and prior_count > 0:
        fp = f'volume_spike:{day_key}'
        if not _existing(brand.id, fp, dedupe_since):
            created.append(Alert(
                brand_id=brand.id, kind='volume_spike', severity='warning', fingerprint=fp,
                message=(f'Mention volume jumped to {len(recent)} in {window_hours}h '
                         f'(up from {prior_count} the window before).'),
            ))

    # 2. Negative sentiment concentration
    negatives = [m for m in recent if m.sentiment_label == 'negative']
    if len(negatives) >= NEGATIVE_FLOOR and recent:
        share = len(negatives) / len(recent)
        if share >= NEGATIVE_SHARE_THRESHOLD:
            fp = f'negative_spike:{day_key}'
            if not _existing(brand.id, fp, dedupe_since):
                created.append(Alert(
                    brand_id=brand.id, kind='negative_spike', severity='critical', fingerprint=fp,
                    message=(f'{len(negatives)} of {len(recent)} mentions ({share:.0%}) are negative '
                             f'in the last {window_hours}h.'),
                ))

    # 3. A single outsized mention
    if len(recent) >= 3:
        mean_reach = sum(m.reach or 0 for m in recent) / len(recent)
        if mean_reach > 0:
            for m in recent:
                if (m.reach or 0) >= mean_reach * VIRAL_REACH_MULTIPLE:
                    fp = f'viral_mention:{m.id}'
                    if not _existing(brand.id, fp, now - timedelta(days=30)):
                        created.append(Alert(
                            brand_id=brand.id, kind='viral_mention',
                            severity='critical' if m.sentiment_label == 'negative' else 'info',
                            fingerprint=fp,
                            message=(f'High-reach {m.sentiment_label} mention on '
                                     f'{m.source_label or m.source_kind}: "{(m.title or m.snippet)[:110]}"'),
                        ))

    for alert in created:
        db.session.add(alert)
    if created:
        db.session.commit()

    return created
