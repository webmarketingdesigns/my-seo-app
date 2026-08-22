"""RSS and Atom adapter, parsed with the standard library only.

Covers news sites, blogs, Google News queries, YouTube channel feeds and Reddit
RSS — a wide net for zero API keys.
"""
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from .base import SourceError, http_get, raw_item, stable_id, strip_html

NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'content': 'http://purl.org/rss/1.0/modules/content/',
    'dc': 'http://purl.org/dc/elements/1.1/',
}
DATE_FORMATS = ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d')


def _parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed:
            return parsed.replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _text(element, *paths):
    for path in paths:
        try:
            found = element.find(path, NS)
        except SyntaxError:
            # The feed does not declare this prefix; try the next path.
            continue
        if found is not None:
            if found.text:
                return found.text
            href = found.get('href')
            if href:
                return href
    return ''


def parse_feed(content, config, fallback_label='', prefix='rss') -> list:
    """Parse RSS or Atom bytes into raw items. Shared with adapters that fall
    back to a feed URL when their JSON API is unavailable."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise SourceError(f'Malformed feed: {exc}') from exc

    entries = root.findall('.//item') or root.findall('.//atom:entry', NS)
    feed_title = _text(root, './channel/title', './atom:title') or fallback_label

    items = []
    for entry in entries[: config['MAX_ITEMS_PER_SOURCE']]:
        title = strip_html(_text(entry, 'title', 'atom:title'))
        link = _text(entry, 'link', 'atom:link')
        body = strip_html(
            _text(entry, 'description', 'content:encoded', 'atom:summary', 'atom:content')
        )
        published = _parse_date(
            _text(entry, 'pubDate', 'atom:published', 'atom:updated', 'dc:date')
        )
        author = strip_html(_text(entry, 'author', 'atom:author/atom:name', 'dc:creator'))
        guid = _text(entry, 'guid', 'atom:id') or link or title

        items.append(raw_item(
            external_id=stable_id(prefix, guid),
            title=title,
            content=body or title,
            url=link,
            author=author,
            published_at=published,
            # RSS exposes no audience figure; reach stays 0 rather than inventing one.
            reach=0,
            source_label=strip_html(feed_title),
        ))
    return items


def fetch(source, config) -> list:
    url = (source.config or '').strip()
    if not url:
        raise SourceError('No feed URL configured')
    response = http_get(url, config)
    return parse_feed(response.content, config, fallback_label=source.label or url)
