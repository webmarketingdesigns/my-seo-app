"""Derive a brand voice profile from the brand's own website.

This is the step native.no calls "brand analysis": before generating anything,
read what the company already says about itself so the output sounds like them.
The heuristics are deliberately transparent — tone is inferred from measurable
signals (sentence length, pronouns, exclamation density) rather than guessed.
"""
import re

import requests

from ..analysis.topics import STOPWORDS, extract_terms
from ..ingest.base import strip_html

TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL
)
OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL
)
HEADING_RE = re.compile(r'<h[12][^>]*>(.*?)</h[12]>', re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r'<(script|style|nav|footer)[^>]*>.*?</\1>', re.IGNORECASE | re.DOTALL)
SENTENCE_RE = re.compile(r'[.!?]+')

FIRST_PERSON = {'we', 'our', 'us', "we're", "we've", 'ours'}
SECOND_PERSON = {'you', 'your', "you're", 'yours'}

AUDIENCE_HINTS = [
    (('enterprise', 'compliance', 'procurement', 'governance', 'soc 2'), 'enterprise buyers'),
    (('developer', 'api', 'sdk', 'documentation', 'open source'), 'developers and technical teams'),
    (('agency', 'client', 'retainer', 'freelance'), 'agencies and consultants'),
    (('small business', 'solo', 'startup', 'founder', 'smb'), 'founders and small teams'),
    (('marketer', 'campaign', 'brand', 'social media', 'content'), 'marketing teams'),
    (('shopper', 'store', 'ecommerce', 'checkout', 'cart'), 'ecommerce operators'),
]

DEFAULT_VOICE = {
    'tone': 'professional but plain-spoken',
    'audience': 'marketing teams',
    'pillars': [],
    'summary': '',
    'vocabulary': [],
    'source': 'default',
}


def _tone_from(text: str) -> str:
    sentences = [s.strip() for s in SENTENCE_RE.split(text) if len(s.strip()) > 12]
    if not sentences:
        return DEFAULT_VOICE['tone']

    words = text.lower().split()
    avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
    exclaim_rate = text.count('!') / max(len(sentences), 1)
    second = sum(1 for w in words if w.strip('.,!?') in SECOND_PERSON) / max(len(words), 1)
    first = sum(1 for w in words if w.strip('.,!?') in FIRST_PERSON) / max(len(words), 1)

    traits = []
    traits.append('punchy and direct' if avg_len < 14 else
                  'considered and detailed' if avg_len > 24 else 'clear and measured')
    if exclaim_rate > 0.25:
        traits.append('energetic')
    if second > 0.02:
        traits.append('speaks directly to the reader')
    elif first > 0.02:
        traits.append('company-voiced ("we")')
    return ', '.join(traits)


def _audience_from(text: str) -> str:
    lowered = text.lower()
    scores = [
        (sum(lowered.count(hint) for hint in hints), audience)
        for hints, audience in AUDIENCE_HINTS
    ]
    score, audience = max(scores, key=lambda pair: pair[0])
    return audience if score else DEFAULT_VOICE['audience']


def analyse_text(text: str, brand_name: str = '', headings=None, summary: str = '') -> dict:
    """Build a voice profile from already-extracted page text."""
    headings = headings or []
    ignore = {w.lower() for w in brand_name.split()} | STOPWORDS

    terms = extract_terms([text], top_n=30, ignore=ignore)
    # Pillars come from headings where possible — they are what the company chose
    # to put in large type — and fall back to frequent body terms.
    pillars = [h for h in headings if 3 <= len(h.split()) <= 8][:4]
    if len(pillars) < 4:
        pillars += [term for term, _ in terms if ' ' in term][: 4 - len(pillars)]
    if len(pillars) < 4:
        pillars += [term for term, _ in terms][: 4 - len(pillars)]

    return {
        'tone': _tone_from(text),
        'audience': _audience_from(text),
        'pillars': [p.strip()[:80] for p in pillars if p.strip()][:5],
        'summary': summary.strip()[:400],
        'vocabulary': [term for term, _ in terms[:12]],
        'source': 'website',
    }


def analyse_site(url: str, config, brand_name: str = '') -> dict:
    """Fetch a homepage and derive the voice profile. Never raises."""
    if not url:
        return dict(DEFAULT_VOICE)
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        response = requests.get(
            url,
            timeout=config['HTTP_TIMEOUT'],
            headers={'User-Agent': config['HTTP_USER_AGENT']},
        )
        response.raise_for_status()
        html = response.text
    except requests.RequestException as exc:
        profile = dict(DEFAULT_VOICE)
        profile['error'] = f'Could not fetch {url}: {type(exc).__name__}'
        return profile

    body = SCRIPT_RE.sub(' ', html)
    headings = [strip_html(h) for h in HEADING_RE.findall(body)]
    title = strip_html(TITLE_RE.search(html).group(1)) if TITLE_RE.search(html) else ''
    desc_match = META_DESC_RE.search(html) or OG_DESC_RE.search(html)
    summary = strip_html(desc_match.group(1)) if desc_match else title

    text = strip_html(body)[:20000]
    profile = analyse_text(text, brand_name=brand_name, headings=headings, summary=summary)
    profile['title'] = title[:200]
    profile['url'] = url
    return profile
