"""Database models for BrandLoop.

The schema follows the product loop: a Brand owns Keywords and Sources, which
produce Mentions; Mentions feed topics that produce Posts, which publish to
channels and accrue PostMetrics. Alerts are derived signals worth interrupting
a human for.
"""
import json
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


CHANNELS = {
    'x': {'label': 'X', 'max_chars': 280, 'max_hashtags': 2},
    'linkedin': {'label': 'LinkedIn', 'max_chars': 2200, 'max_hashtags': 3},
    'instagram': {'label': 'Instagram', 'max_chars': 2200, 'max_hashtags': 8},
    'facebook': {'label': 'Facebook', 'max_chars': 2000, 'max_hashtags': 3},
    'tiktok': {'label': 'TikTok', 'max_chars': 2200, 'max_hashtags': 5},
    'threads': {'label': 'Threads', 'max_chars': 500, 'max_hashtags': 3},
}

SOURCE_KINDS = ('rss', 'hackernews', 'reddit', 'seed')


class Brand(db.Model):
    __tablename__ = 'brands'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    website = db.Column(db.String(300), default='')
    description = db.Column(db.Text, default='')
    voice_json = db.Column(db.Text, default='')  # BrandVoice profile, see generate.brandvoice
    created_at = db.Column(db.DateTime, default=utcnow)

    keywords = db.relationship('Keyword', backref='brand', cascade='all, delete-orphan', lazy='select')
    sources = db.relationship('Source', backref='brand', cascade='all, delete-orphan', lazy='select')

    @property
    def voice(self) -> dict:
        try:
            return json.loads(self.voice_json) if self.voice_json else {}
        except (ValueError, TypeError):
            return {}

    @voice.setter
    def voice(self, value: dict):
        self.voice_json = json.dumps(value)

    def terms(self, kind: str) -> list:
        return [k.term for k in self.keywords if k.kind == kind]

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'website': self.website,
            'description': self.description,
            'voice': self.voice,
            'keywords': [k.to_dict() for k in self.keywords],
        }


class Keyword(db.Model):
    """A term the brand tracks. `kind` splits the boolean query into parts."""

    __tablename__ = 'keywords'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False, index=True)
    term = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default='include')  # include | exclude | competitor
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {'id': self.id, 'term': self.term, 'kind': self.kind}


class Source(db.Model):
    """A configured feed to poll. `config` holds the URL or query for the adapter."""

    __tablename__ = 'sources'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    label = db.Column(db.String(160), default='')
    config = db.Column(db.String(500), default='')
    enabled = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    last_result = db.Column(db.String(300), default='')

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'label': self.label,
            'config': self.config,
            'enabled': self.enabled,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_result': self.last_result,
        }


class Mention(db.Model):
    """One piece of matched content from any source."""

    __tablename__ = 'mentions'
    __table_args__ = (
        db.UniqueConstraint('brand_id', 'external_id', name='uq_mention_brand_external'),
        db.Index('ix_mention_brand_published', 'brand_id', 'published_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    external_id = db.Column(db.String(200), nullable=False)
    source_kind = db.Column(db.String(30), nullable=False, default='seed')
    source_label = db.Column(db.String(160), default='')
    author = db.Column(db.String(160), default='')
    title = db.Column(db.String(500), default='')
    content = db.Column(db.Text, default='')
    url = db.Column(db.String(600), default='')
    published_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    reach = db.Column(db.Integer, default=0)
    sentiment_score = db.Column(db.Float, default=0.0)   # -1.0 .. 1.0
    sentiment_label = db.Column(db.String(12), default='neutral')
    matched_terms = db.Column(db.String(400), default='')  # comma separated
    subject = db.Column(db.String(120), default='')        # brand name or competitor term
    is_competitor = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def terms(self) -> list:
        return [t for t in (self.matched_terms or '').split(',') if t]

    @property
    def snippet(self) -> str:
        text = (self.content or '').strip()
        return text[:280] + ('…' if len(text) > 280 else '')

    def to_dict(self):
        return {
            'id': self.id,
            'source_kind': self.source_kind,
            'source_label': self.source_label,
            'author': self.author,
            'title': self.title,
            'snippet': self.snippet,
            'url': self.url,
            'published_at': self.published_at.isoformat(),
            'reach': self.reach,
            'sentiment_score': round(self.sentiment_score or 0.0, 3),
            'sentiment_label': self.sentiment_label,
            'terms': self.terms,
            'subject': self.subject,
            'is_competitor': self.is_competitor,
        }


class Post(db.Model):
    """A generated social post moving through draft → approved → scheduled → published."""

    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False, default='linkedin')
    body = db.Column(db.Text, nullable=False, default='')
    hashtags = db.Column(db.String(300), default='')
    status = db.Column(db.String(20), nullable=False, default='draft', index=True)
    angle = db.Column(db.String(40), default='')          # insight | question | tip | contrarian | news
    topic = db.Column(db.String(160), default='')          # trending term that seeded the post
    source_mention_id = db.Column(db.Integer, db.ForeignKey('mentions.id'))
    generator = db.Column(db.String(30), default='template')  # template | anthropic
    scheduled_for = db.Column(db.DateTime)
    published_at = db.Column(db.DateTime)
    external_url = db.Column(db.String(600), default='')
    created_at = db.Column(db.DateTime, default=utcnow)

    metrics = db.relationship('PostMetric', backref='post', cascade='all, delete-orphan', lazy='select')

    @property
    def hashtag_list(self) -> list:
        return [h for h in (self.hashtags or '').split(' ') if h]

    @property
    def full_text(self) -> str:
        return (self.body + ('\n\n' + self.hashtags if self.hashtags else '')).strip()

    @property
    def latest_metric(self):
        if not self.metrics:
            return None
        return max(self.metrics, key=lambda m: m.captured_at or datetime.min)

    def to_dict(self):
        metric = self.latest_metric
        return {
            'id': self.id,
            'channel': self.channel,
            'channel_label': CHANNELS.get(self.channel, {}).get('label', self.channel),
            'body': self.body,
            'hashtags': self.hashtag_list,
            'full_text': self.full_text,
            'char_count': len(self.full_text),
            'status': self.status,
            'angle': self.angle,
            'topic': self.topic,
            'generator': self.generator,
            'scheduled_for': self.scheduled_for.isoformat() if self.scheduled_for else None,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'external_url': self.external_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'metrics': metric.to_dict() if metric else None,
        }


class PostMetric(db.Model):
    __tablename__ = 'post_metrics'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    impressions = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    comments = db.Column(db.Integer, default=0)
    shares = db.Column(db.Integer, default=0)
    clicks = db.Column(db.Integer, default=0)
    captured_at = db.Column(db.DateTime, default=utcnow)

    @property
    def engagements(self) -> int:
        return (self.likes or 0) + (self.comments or 0) + (self.shares or 0) + (self.clicks or 0)

    @property
    def engagement_rate(self) -> float:
        return (self.engagements / self.impressions) if self.impressions else 0.0

    def to_dict(self):
        return {
            'impressions': self.impressions,
            'likes': self.likes,
            'comments': self.comments,
            'shares': self.shares,
            'clicks': self.clicks,
            'engagements': self.engagements,
            'engagement_rate': round(self.engagement_rate, 4),
            'captured_at': self.captured_at.isoformat() if self.captured_at else None,
        }


class Alert(db.Model):
    __tablename__ = 'alerts'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)      # volume_spike | negative_spike | viral_mention
    severity = db.Column(db.String(10), default='info')  # info | warning | critical
    message = db.Column(db.String(400), nullable=False)
    fingerprint = db.Column(db.String(120), default='', index=True)  # dedupes repeat firings
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'severity': self.severity,
            'message': self.message,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
