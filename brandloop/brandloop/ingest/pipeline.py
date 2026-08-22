"""The ingestion pipeline: fetch → match → score → persist.

Adapters know nothing about brands or sentiment; this module owns the boolean
query semantics (include / exclude / competitor terms), sentiment scoring and
deduplication, so every source is treated identically.
"""
import re

from sqlalchemy.exc import IntegrityError

from ..analysis.sentiment import label_for, score_text
from ..models import Mention, Source, db, utcnow
from . import hackernews, reddit, rss, seed
from .base import SourceError

ADAPTERS = {
    'rss': rss.fetch,
    'hackernews': hackernews.fetch,
    'reddit': reddit.fetch,
}


def _term_pattern(term: str):
    """Word-boundary match so 'native' does not match 'alternative'."""
    return re.compile(r'(?<![\w])' + re.escape(term.strip()) + r'(?![\w])', re.IGNORECASE)


def _compile_terms(brand):
    return (
        [(t, _term_pattern(t)) for t in brand.terms('include') if t.strip()],
        [(t, _term_pattern(t)) for t in brand.terms('exclude') if t.strip()],
        [(t, _term_pattern(t)) for t in brand.terms('competitor') if t.strip()],
    )


def match_item(item: dict, includes, excludes, competitors, brand_name: str):
    """Return (matched_terms, subject, is_competitor) or None when the item is out of scope."""
    haystack = f"{item.get('title', '')} {item.get('content', '')}"

    for _, pattern in excludes:
        if pattern.search(haystack):
            return None

    include_hits = [term for term, pattern in includes if pattern.search(haystack)]
    competitor_hits = [term for term, pattern in competitors if pattern.search(haystack)]

    if not include_hits and not competitor_hits:
        return None

    hinted = item.get('subject')
    if hinted:
        is_competitor = hinted.lower() != brand_name.lower()
        subject = hinted
    else:
        # With no hint, an item that names only a competitor belongs to them;
        # anything naming us (even alongside a rival) counts as ours.
        is_competitor = not include_hits
        subject = competitor_hits[0] if is_competitor else brand_name

    return include_hits + competitor_hits, subject, is_competitor


def persist_items(brand, items, source_kind: str, includes=None, excludes=None,
                  competitors=None) -> dict:
    """Score and store matching items. Returns counts of stored / skipped / duplicate."""
    if includes is None:
        includes, excludes, competitors = _compile_terms(brand)

    stored = skipped = duplicate = 0
    existing = {
        row[0]
        for row in db.session.query(Mention.external_id).filter(Mention.brand_id == brand.id).all()
    }

    for item in items:
        match = match_item(item, includes, excludes, competitors, brand.name)
        if match is None:
            skipped += 1
            continue

        terms, subject, is_competitor = match
        if item['external_id'] in existing:
            duplicate += 1
            continue
        existing.add(item['external_id'])

        # Many feeds repeat the headline as the first line of the body. Scoring
        # both would double-count every word in the title.
        title = (item.get('title') or '').strip()
        content = (item.get('content') or '').strip()
        text = content if title and title.lower() in content.lower() else f'{title}. {content}'
        score = score_text(text)

        db.session.add(Mention(
            brand_id=brand.id,
            external_id=item['external_id'],
            source_kind=source_kind,
            source_label=item.get('source_label', ''),
            author=item.get('author', ''),
            title=item.get('title', ''),
            content=item.get('content', ''),
            url=item.get('url', ''),
            published_at=item.get('published_at') or utcnow(),
            reach=item.get('reach', 0),
            sentiment_score=score,
            sentiment_label=label_for(score),
            matched_terms=','.join(terms[:8]),
            subject=subject,
            is_competitor=is_competitor,
        ))
        stored += 1

    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent run inserted the same external_id; the unique constraint
        # is the source of truth, so drop this batch's tail rather than crash.
        db.session.rollback()
        return {'stored': 0, 'skipped': skipped, 'duplicate': duplicate + stored}

    return {'stored': stored, 'skipped': skipped, 'duplicate': duplicate}


def run_source(brand, source, config) -> dict:
    """Fetch and persist one source, recording the outcome on the source row."""
    adapter = ADAPTERS.get(source.kind)
    result = {'source_id': source.id, 'kind': source.kind, 'label': source.label,
              'stored': 0, 'skipped': 0, 'duplicate': 0, 'error': None}

    if adapter is None:
        result['error'] = f'No adapter for source kind "{source.kind}"'
    else:
        try:
            items = adapter(source, config)
            result.update(persist_items(brand, items, source.kind))
        except SourceError as exc:
            result['error'] = str(exc)
        except Exception as exc:  # an adapter bug must not take down the whole run
            result['error'] = f'{type(exc).__name__}: {exc}'

    source.last_run_at = utcnow()
    source.last_result = (result['error'] or f"stored {result['stored']}, "
                          f"skipped {result['skipped']}, dupes {result['duplicate']}")[:300]
    db.session.commit()
    return result


def run_ingestion(brand, config) -> dict:
    """Run every enabled source for a brand."""
    sources = Source.query.filter(Source.brand_id == brand.id, Source.enabled.is_(True)).all()
    results = [run_source(brand, source, config) for source in sources]
    return {
        'brand': brand.name,
        'sources_run': len(results),
        'stored': sum(r['stored'] for r in results),
        'skipped': sum(r['skipped'] for r in results),
        'duplicate': sum(r['duplicate'] for r in results),
        'errors': [f"{r['label'] or r['kind']}: {r['error']}" for r in results if r['error']],
        'results': results,
    }


def run_seed(brand, now, days: int = 30, per_day: int = 6) -> dict:
    """Populate the brand with synthetic-but-plausible chatter."""
    items = seed.generate(brand.name, brand.terms('competitor'), now, days=days, per_day=per_day)
    return persist_items(brand, items, 'seed')
