"""Reddit adapter.

The JSON search endpoint returns richer data (score, comment count → reach) but
Reddit blocks unauthenticated traffic from many networks with a 403. The public
RSS endpoint is not blocked, so we fall back to it and accept the thinner data
rather than losing the source. If both fail the pipeline records the error
against the source and carries on.
"""
from datetime import datetime

from . import rss
from .base import SourceError, http_get, raw_item, stable_id, strip_html

ENDPOINT = 'https://www.reddit.com/search.json'
RSS_ENDPOINT = 'https://www.reddit.com/search.rss'


def fetch(source, config) -> list:
    query = (source.config or '').strip()
    if not query:
        raise SourceError('No search query configured')

    params = {
        'q': query,
        'sort': 'new',
        'limit': min(config['MAX_ITEMS_PER_SOURCE'], 100),
        't': 'month',
    }
    try:
        response = http_get(ENDPOINT, config, params=params)
        children = response.json().get('data', {}).get('children', [])
    except SourceError:
        return _fetch_via_rss(query, config)
    except ValueError as exc:
        raise SourceError(f'Bad JSON from Reddit: {exc}') from exc

    items = []
    for child in children:
        post = child.get('data', {})
        created = post.get('created_utc')
        subreddit = post.get('subreddit', '')
        items.append(raw_item(
            external_id=stable_id('reddit', post.get('id')),
            title=strip_html(post.get('title', '')),
            content=strip_html(post.get('selftext') or post.get('title', '')),
            url='https://www.reddit.com' + post.get('permalink', ''),
            author=post.get('author', ''),
            published_at=datetime.utcfromtimestamp(created) if created else None,
            reach=int(post.get('score') or 0) * 100 + int(post.get('num_comments') or 0) * 50,
            source_label=f'r/{subreddit}' if subreddit else 'Reddit',
        ))
    return items


def _fetch_via_rss(query: str, config) -> list:
    """Thinner fallback: no score or comment count, so reach stays 0."""
    response = http_get(RSS_ENDPOINT, config, params={'q': query, 'sort': 'new'})
    return rss.parse_feed(response.content, config, fallback_label='Reddit', prefix='reddit')
