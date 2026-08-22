"""Anthropic-backed copy generation.

Optional by design: with no API key configured the composer falls back to its
template engine, so the whole product works offline and on a free tier. Every
failure path here returns None rather than raising, because a generation
hiccup should never take down the studio page.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# Model choice is configurable, but the default is Anthropic's most capable
# general model — social copy is short, so the cost per post is negligible.
DEFAULT_MODEL = 'claude-opus-5'
MAX_TOKENS = 4096

_JSON_BLOCK_RE = re.compile(r'\[.*\]', re.DOTALL)


def is_configured(config) -> bool:
    return bool(config.get('ANTHROPIC_API_KEY'))


def _client(config):
    try:
        import anthropic
    except ImportError:
        logger.warning('anthropic SDK is not installed; using the template composer')
        return None, None
    return anthropic, anthropic.Anthropic(api_key=config['ANTHROPIC_API_KEY'])


SYSTEM_PROMPT = """You are a senior social media copywriter working inside a brand \
monitoring tool. You write posts that sound like a real person at the company, not \
like an ad.

Rules:
- Match the brand voice, audience and content pillars you are given.
- One idea per post. No filler openers ("In today's fast-paced world").
- Never invent statistics, customer names, awards, or product capabilities. If you \
need a specific number you do not have, write the post without it.
- Respect the character limit for the channel, including hashtags.
- Hashtags go in a separate field, never inside the body.

Respond with ONLY a JSON array, no prose and no code fences. Each element:
{"channel": "<channel id>", "angle": "<insight|question|tip|contrarian|news>", \
"body": "<post text>", "hashtags": ["#One", "#Two"]}"""


def _build_prompt(brand, voice, topic, channels, evidence) -> str:
    pillars = ', '.join(voice.get('pillars', [])) or 'not specified'
    audience = voice.get('audience') or 'not specified'
    tone = voice.get('tone') or 'professional but plain-spoken'

    channel_specs = '\n'.join(
        f'- {cid}: max {spec["max_chars"]} characters, at most {spec["max_hashtags"]} hashtags'
        for cid, spec in channels.items()
    )
    quotes = '\n'.join(f'- "{e}"' for e in evidence[:6]) or '- (no direct quotes available)'

    return f"""Brand: {brand.name}
Website: {brand.website or 'n/a'}
What they do: {brand.description or voice.get('summary') or 'n/a'}
Audience: {audience}
Tone: {tone}
Content pillars: {pillars}

Trending topic to write about: "{topic}"

What people are actually saying about it right now:
{quotes}

Write one post per channel for these channels:
{channel_specs}

Use a different angle for each channel. Ground the posts in the quotes above — \
they are the reason this topic is worth posting about."""


def generate_posts(config, brand, voice, topic, channels, evidence):
    """Return a list of post dicts, or None if generation is unavailable/failed."""
    if not is_configured(config):
        return None

    anthropic, client = _client(config)
    if client is None:
        return None

    try:
        response = client.beta.messages.create(
            model=config.get('ANTHROPIC_MODEL') or DEFAULT_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            # Server-side fallbacks: if a safety classifier declines the request,
            # the API retries it on a fallback model inside the same call rather
            # than leaving the studio with nothing to show.
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
            output_config={'effort': 'medium'},
            messages=[{'role': 'user', 'content': _build_prompt(brand, voice, topic, channels, evidence)}],
        )
    except Exception as exc:  # network, auth, rate limit — all degrade to templates
        logger.warning('Anthropic generation failed (%s); falling back to templates', exc)
        return None

    if getattr(response, 'stop_reason', None) == 'refusal':
        logger.warning('Anthropic declined the generation request; falling back to templates')
        return None

    text = ''.join(block.text for block in response.content if block.type == 'text').strip()
    return _parse(text)


def _parse(text: str):
    """Pull the JSON array out of the response, tolerating stray prose."""
    if not text:
        return None
    candidate = text
    if not candidate.lstrip().startswith('['):
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            logger.warning('No JSON array found in model response')
            return None
        candidate = match.group(0)

    try:
        parsed = json.loads(candidate)
    except ValueError as exc:
        logger.warning('Could not parse model response as JSON: %s', exc)
        return None

    if not isinstance(parsed, list):
        return None

    posts = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get('body'):
            continue
        hashtags = item.get('hashtags') or []
        if isinstance(hashtags, str):
            hashtags = hashtags.split()
        posts.append({
            'channel': item.get('channel', 'linkedin'),
            'angle': item.get('angle', 'insight'),
            'body': str(item['body']).strip(),
            'hashtags': [str(h).strip() for h in hashtags if str(h).strip()],
        })
    return posts or None
