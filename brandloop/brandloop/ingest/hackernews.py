"""Hacker News adapter via the public Algolia search API (no key required)."""
from datetime import datetime

from .base import SourceError, http_get, raw_item, stable_id, strip_html

ENDPOINT = 'https://hn.algolia.com/api/v1/search_by_date'


def fetch(source, config) -> list:
    query = (source.config or '').strip()
    if not query:
        raise SourceError('No search query configured')

    response = http_get(ENDPOINT, config, params={
        'query': query,
        'tags': '(story,comment)',
        'hitsPerPage': min(config['MAX_ITEMS_PER_SOURCE'], 50),
    })
    try:
        hits = response.json().get('hits', [])
    except ValueError as exc:
        raise SourceError(f'Bad JSON from Hacker News: {exc}') from exc

    items = []
    for hit in hits:
        title = hit.get('title') or hit.get('story_title') or ''
        body = strip_html(hit.get('comment_text') or hit.get('story_text') or '')
        object_id = hit.get('objectID')
        created = hit.get('created_at_i')
        published = datetime.utcfromtimestamp(created) if created else None

        # Points and comment count are the closest thing HN gives us to audience size.
        points = hit.get('points') or 0
        num_comments = hit.get('num_comments') or 0

        items.append(raw_item(
            external_id=stable_id('hn', object_id),
            title=strip_html(title),
            content=body or strip_html(title),
            url=hit.get('url') or f'https://news.ycombinator.com/item?id={object_id}',
            author=hit.get('author', ''),
            published_at=published,
            reach=(points * 120) + (num_comments * 60),
            source_label='Hacker News',
        ))
    return items
