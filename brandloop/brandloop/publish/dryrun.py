"""Dry-run publisher.

Every real channel needs an approved platform app and OAuth tokens, which is a
procurement problem rather than a code problem. This adapter completes the loop
end to end — posts move to published, get a permalink and start accruing
metrics — so scheduling and analytics are exercisable before any API access
exists. Swap it out per channel in PUBLISHERS as real credentials land.
"""
from ..ingest.base import stable_id

BASE_URLS = {
    'x': 'https://x.com/{handle}/status/{ref}',
    'linkedin': 'https://www.linkedin.com/feed/update/urn:li:activity:{ref}',
    'instagram': 'https://www.instagram.com/p/{ref}',
    'facebook': 'https://www.facebook.com/{handle}/posts/{ref}',
    'tiktok': 'https://www.tiktok.com/@{handle}/video/{ref}',
    'threads': 'https://www.threads.net/@{handle}/post/{ref}',
}


def _handle(brand) -> str:
    return ''.join(c for c in (brand.name or 'brand').lower() if c.isalnum()) or 'brand'


def publish(post, brand, config) -> dict:
    ref = stable_id('publish', post.id, post.channel)[:16]
    template = BASE_URLS.get(post.channel, 'https://example.com/{handle}/{ref}')
    return {
        'external_url': template.format(handle=_handle(brand), ref=ref),
        'simulated': True,
    }
