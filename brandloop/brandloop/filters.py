"""Jinja filters and globals shared by every template."""
from datetime import datetime, timezone

from .models import CHANNELS


def _ago(value) -> str:
    if not value:
        return '—'
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = now - value
    seconds = delta.total_seconds()
    if seconds < 0:
        seconds = abs(seconds)
        suffix = 'from now'
    else:
        suffix = 'ago'
    for limit, div, unit in ((60, 1, 's'), (3600, 60, 'm'), (86400, 3600, 'h'), (2592000, 86400, 'd')):
        if seconds < limit:
            return f'{int(seconds // div)}{unit} {suffix}'
    return value.strftime('%b %d, %Y')


def _compact(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return '0'
    for limit, div, unit in ((1_000_000_000, 1_000_000_000, 'B'), (1_000_000, 1_000_000, 'M'), (10_000, 1_000, 'k')):
        if abs(n) >= limit:
            return f'{n / div:.1f}{unit}'.replace('.0', '')
    return f'{int(n):,}'


def _pct(value, digits=0) -> str:
    try:
        return f'{float(value or 0) * 100:.{digits}f}%'
    except (TypeError, ValueError):
        return '0%'


def _signed(value, digits=0) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return '0'
    return f'{"+" if n > 0 else ""}{n:.{digits}f}'


def register(app):
    app.jinja_env.filters['ago'] = _ago
    app.jinja_env.filters['compact'] = _compact
    app.jinja_env.filters['pct'] = _pct
    app.jinja_env.filters['signed'] = _signed
    app.jinja_env.globals['CHANNELS'] = CHANNELS
    app.jinja_env.globals['now'] = lambda: datetime.now(timezone.utc).replace(tzinfo=None)
