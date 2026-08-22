"""Source adapter contract.

Every adapter turns some external feed into a list of RawItem dicts. Keeping the
shape uniform is what lets the pipeline treat a paid firehose and a free RSS
feed identically — swapping in an X or Meta API later means writing one adapter,
not touching the pipeline.
"""
import hashlib
import re
from datetime import datetime, timezone

import requests

_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


class SourceError(RuntimeError):
    """Raised when a source cannot be fetched. The pipeline records and moves on."""


def raw_item(external_id, title='', content='', url='', author='', published_at=None,
             reach=0, source_label='', subject=None) -> dict:
    """`subject` lets an adapter state who the item is about when it already
    knows; otherwise the pipeline infers it from which tracked terms matched."""
    return {
        'subject': subject,
        'external_id': str(external_id)[:200],
        'title': (title or '')[:500],
        'content': content or '',
        'url': (url or '')[:600],
        'author': (author or '')[:160],
        'published_at': published_at or datetime.now(timezone.utc).replace(tzinfo=None),
        'reach': int(reach or 0),
        'source_label': (source_label or '')[:160],
    }


def strip_html(text: str) -> str:
    return _WS_RE.sub(' ', _TAG_RE.sub(' ', text or '')).strip()


def stable_id(*parts) -> str:
    return hashlib.sha1('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:32]


def http_get(url: str, config, params=None):
    try:
        response = requests.get(
            url,
            params=params,
            timeout=config['HTTP_TIMEOUT'],
            headers={'User-Agent': config['HTTP_USER_AGENT'], 'Accept': '*/*'},
        )
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        raise SourceError(f'{type(exc).__name__}: {exc}') from exc
