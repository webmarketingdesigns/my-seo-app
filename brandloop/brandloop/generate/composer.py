"""Turn trending topics into channel-ready drafts.

Two engines sit behind one interface. The template engine is deterministic, free
and always available; the Anthropic engine produces better copy when a key is
configured. Both emit the same shape, so the approval queue does not care which
one wrote a post.
"""
import random
from datetime import timedelta

from ..analysis.topics import trending_terms
from ..models import CHANNELS, Mention, Post, db, utcnow
from . import llm

ANGLES = ('insight', 'question', 'tip', 'contrarian', 'news')

# Each pattern is a full post skeleton. They are written to survive substitution
# with an awkward topic phrase, which is why none of them end mid-sentence.
PATTERNS = {
    'insight': [
        "{topic_title} keeps coming up in conversations about {pillar}.\n\n"
        "What we're seeing: the teams that get this right treat it as a workflow problem, "
        "not a tooling problem. The tool only helps once someone owns the outcome.\n\n"
        "Worth a look if {pillar} is on your roadmap this quarter.",

        "Noticed a shift this week: people are talking about {topic} far more than they were "
        "a month ago.\n\nThat usually means one of two things — either it just got easier, "
        "or it just got painful enough to complain about publicly. Both are worth paying "
        "attention to if you work in {pillar}.",
    ],
    'question': [
        "Genuine question for anyone working on {pillar}: how are you handling {topic}?\n\n"
        "We keep seeing the same three approaches and none of them feel obviously right. "
        "Curious what's actually working for you.",

        "{topic_title} — overhyped, or underrated?\n\n"
        "We've heard strong arguments both ways this month. If you've shipped something here, "
        "we'd like to hear how it went.",
    ],
    'tip': [
        "If {topic} is on your list, start here:\n\n"
        "1. Write down what \"done\" looks like before you evaluate anything.\n"
        "2. Pick the one metric you'd defend in a review.\n"
        "3. Run it for two weeks before you add a second tool.\n\n"
        "Most of the wasted effort we see happens because step 1 got skipped.",

        "Quick note on {topic}: the hardest part usually isn't the setup, it's deciding "
        "who reads the output every week.\n\n"
        "Assign that person first. Everything else in {pillar} gets easier afterwards.",
    ],
    'contrarian': [
        "Unpopular take: most teams don't have {article} {topic} problem. They have a "
        "\"nobody looks at it\" problem.\n\n"
        "Adding another dashboard won't fix that. Deciding who acts on it will.",

        "Everyone's talking about {topic} right now. Before you buy anything — can your team "
        "already answer the question you'd use it to answer?\n\n"
        "If yes, you have a process gap, not a tooling gap.",
    ],
    'news': [
        "{topic_title} is trending in our space this week.\n\n"
        "Here's the short version of what people are saying, and why it matters if you own "
        "{pillar}. Full breakdown in the comments.",

        "Tracking a spike in conversation around {topic} over the last few days.\n\n"
        "Still early, but the direction is consistent enough to plan around. We'll keep "
        "watching it.",
    ],
}

HASHTAG_STOP = {'the', 'and', 'for', 'with', 'that', 'this'}

# Words that start with a vowel letter but take "a", and vice versa.
_AN_EXCEPTIONS = ('hour', 'honest', 'honou', 'heir')
_A_EXCEPTIONS = ('user', 'unique', 'unified', 'uni', 'euro', 'one-')


def _article(phrase: str) -> str:
    """Pick "a" or "an" for the phrase that follows it."""
    word = (phrase or '').strip().lower()
    if not word:
        return 'a'
    if word.startswith(_A_EXCEPTIONS):
        return 'a'
    if word.startswith(_AN_EXCEPTIONS):
        return 'an'
    return 'an' if word[0] in 'aeiou' else 'a'


def _hashtags(topic: str, voice: dict, limit: int) -> list:
    """Build hashtags from the topic and the brand's own vocabulary."""
    words = [w for w in topic.replace('-', ' ').split() if w.lower() not in HASHTAG_STOP]
    tags = []
    if words:
        tags.append('#' + ''.join(w.capitalize() for w in words[:3] if w.isalnum()))
    for term in voice.get('vocabulary', []):
        if len(tags) >= limit:
            break
        parts = [p for p in term.split() if p.isalnum()]
        if not parts:
            continue
        tag = '#' + ''.join(p.capitalize() for p in parts[:2])
        if tag not in tags and 3 < len(tag) <= 26:
            tags.append(tag)
    return [t for t in tags if len(t) > 3][:limit]


def _fit(body: str, hashtags: list, max_chars: int) -> tuple:
    """Trim a draft to the channel limit, dropping hashtags before prose."""
    tag_text = ' '.join(hashtags)
    while hashtags and len(body) + len(tag_text) + 2 > max_chars:
        hashtags = hashtags[:-1]
        tag_text = ' '.join(hashtags)

    budget = max_chars - (len(tag_text) + 2 if tag_text else 0)
    if len(body) > budget:
        # Cut at the last sentence boundary that fits, so posts never end mid-word.
        cut = body[:budget]
        for sep in ('\n\n', '. ', ' '):
            idx = cut.rfind(sep)
            if idx > budget * 0.5:
                cut = cut[:idx + (1 if sep == '. ' else 0)]
                break
        body = cut.rstrip() + ('…' if not cut.rstrip().endswith(('.', '!', '?')) else '')
    return body, hashtags


def _template_posts(brand, voice, topic, channels, rng) -> list:
    pillars = voice.get('pillars') or ['your channel mix']
    posts = []
    angles = list(ANGLES)
    rng.shuffle(angles)

    for i, channel in enumerate(channels):
        spec = CHANNELS[channel]
        angle = angles[i % len(angles)]
        pattern = rng.choice(PATTERNS[angle])
        body = pattern.format(
            topic=topic,
            topic_title=topic[0].upper() + topic[1:] if topic else 'This',
            article=_article(topic),
            pillar=rng.choice(pillars),
            brand=brand.name,
        )
        hashtags = _hashtags(topic, voice, spec['max_hashtags'])
        body, hashtags = _fit(body, hashtags, spec['max_chars'])
        posts.append({'channel': channel, 'angle': angle, 'body': body, 'hashtags': hashtags})
    return posts


def _evidence(brand_id: int, topic: str, limit: int = 6) -> list:
    """Real quotes mentioning the topic — what the copy should be grounded in."""
    rows = (
        Mention.query.filter(
            Mention.brand_id == brand_id,
            db.or_(Mention.content.ilike(f'%{topic}%'), Mention.title.ilike(f'%{topic}%')),
        )
        .order_by(Mention.published_at.desc())
        .limit(limit)
        .all()
    )
    return [(m.title or m.snippet)[:220] for m in rows]


def pick_topics(brand, now, limit: int = 5, window_hours: int = 168) -> list:
    """Trending terms for the brand, excluding its own name."""
    mentions = Mention.query.filter(
        Mention.brand_id == brand.id,
        Mention.published_at >= now - timedelta(hours=window_hours * 2),
    ).all()
    ignore = set(brand.name.lower().split()) | {t.lower() for t in brand.terms('include')}
    return trending_terms(mentions, now, window_hours=window_hours, top_n=limit, ignore=ignore)


def generate_drafts(brand, config, topic=None, channels=None, count=1, now=None) -> dict:
    """Create draft posts for a topic (or the top trending topic) and persist them."""
    now = now or utcnow()
    channels = [c for c in (channels or ['linkedin', 'x']) if c in CHANNELS] or ['linkedin']
    voice = brand.voice or {}

    topics = [topic] if topic else [t['term'] for t in pick_topics(brand, now, limit=count)]
    topics = [t for t in topics if t][:max(count, 1)]
    if not topics:
        return {'created': 0, 'generator': 'none', 'topics': [],
                'note': 'No trending topics yet — ingest or seed some mentions first.'}

    rng = random.Random(f'{brand.id}:{now.isoformat()}')
    created = []
    generators = set()

    for term in topics:
        evidence = _evidence(brand.id, term)
        drafts = llm.generate_posts(
            config, brand, voice, term, {c: CHANNELS[c] for c in channels}, evidence
        )
        generator = 'anthropic'
        if not drafts:
            drafts = _template_posts(brand, voice, term, channels, rng)
            generator = 'template'
        generators.add(generator)

        for draft in drafts:
            channel = draft['channel'] if draft['channel'] in CHANNELS else channels[0]
            spec = CHANNELS[channel]
            body, hashtags = _fit(draft['body'], draft.get('hashtags', []), spec['max_chars'])
            post = Post(
                brand_id=brand.id,
                channel=channel,
                body=body,
                hashtags=' '.join(hashtags),
                status='draft',
                angle=draft.get('angle', 'insight'),
                topic=term,
                generator=generator,
                created_at=now,
            )
            db.session.add(post)
            created.append(post)

    db.session.commit()
    return {
        'created': len(created),
        'generator': '+'.join(sorted(generators)),
        'topics': topics,
        'posts': [p.to_dict() for p in created],
    }
