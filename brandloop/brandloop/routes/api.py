"""JSON API. Every mutation the UI performs goes through here."""
from flask import Blueprint, current_app, jsonify, request

from ..analysis.alerts import evaluate_alerts
from ..generate.brandvoice import analyse_site
from ..generate.composer import generate_drafts, pick_topics
from ..ingest.pipeline import run_ingestion, run_seed
from ..models import Alert, Brand, CHANNELS, Keyword, Mention, Post, Source, db, utcnow
from ..scheduler import approve, publish_now, reject, run_due
from .common import current_brand, payload

api_bp = Blueprint('api', __name__)

MAX_SEED_DAYS = 180


def _require_brand():
    brand = current_brand()
    if brand is None:
        return None, (jsonify({'error': 'No brand configured'}), 400)
    return brand, None


@api_bp.get('/health')
def health():
    return jsonify({'status': 'ok', 'brands': Brand.query.count()})


# ---------------------------------------------------------------- brands

@api_bp.post('/brands')
def create_brand():
    data = payload()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400

    brand = Brand(name=name, website=(data.get('website') or '').strip(),
                  description=(data.get('description') or '').strip())
    db.session.add(brand)
    db.session.flush()
    # The brand's own name is always a tracked term; without it nothing matches.
    db.session.add(Keyword(brand_id=brand.id, term=name, kind='include'))
    db.session.commit()
    return jsonify(brand.to_dict()), 201


@api_bp.patch('/brands/<int:brand_id>')
def update_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    data = payload()
    for field in ('name', 'website', 'description'):
        if field in data:
            setattr(brand, field, (data[field] or '').strip())
    db.session.commit()
    return jsonify(brand.to_dict())


@api_bp.post('/brands/<int:brand_id>/analyse-site')
def analyse_brand_site(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    if not brand.website:
        return jsonify({'error': 'Add a website to the brand first'}), 400
    brand.voice = analyse_site(brand.website, current_app.config, brand.name)
    db.session.commit()
    return jsonify({'voice': brand.voice})


# ---------------------------------------------------------------- keywords & sources

@api_bp.post('/keywords')
def create_keyword():
    brand, error = _require_brand()
    if error:
        return error
    data = payload()
    term = (data.get('term') or '').strip()
    kind = data.get('kind', 'include')
    if not term:
        return jsonify({'error': 'term is required'}), 400
    if kind not in ('include', 'exclude', 'competitor'):
        return jsonify({'error': 'invalid kind'}), 400

    keyword = Keyword(brand_id=brand.id, term=term, kind=kind)
    db.session.add(keyword)
    db.session.commit()
    return jsonify(keyword.to_dict()), 201


@api_bp.delete('/keywords/<int:keyword_id>')
def delete_keyword(keyword_id):
    keyword = Keyword.query.get_or_404(keyword_id)
    db.session.delete(keyword)
    db.session.commit()
    return jsonify({'deleted': keyword_id})


@api_bp.post('/sources')
def create_source():
    brand, error = _require_brand()
    if error:
        return error
    data = payload()
    kind = data.get('kind', 'rss')
    config = (data.get('config') or '').strip()
    if kind not in ('rss', 'hackernews', 'reddit'):
        return jsonify({'error': 'invalid source kind'}), 400
    if not config:
        return jsonify({'error': 'a feed URL or search query is required'}), 400

    source = Source(brand_id=brand.id, kind=kind, config=config,
                    label=(data.get('label') or config)[:160])
    db.session.add(source)
    db.session.commit()
    return jsonify(source.to_dict()), 201


@api_bp.patch('/sources/<int:source_id>')
def update_source(source_id):
    source = Source.query.get_or_404(source_id)
    data = payload()
    if 'enabled' in data:
        source.enabled = str(data['enabled']).lower() not in ('false', '0', 'no', '')
    db.session.commit()
    return jsonify(source.to_dict())


@api_bp.delete('/sources/<int:source_id>')
def delete_source(source_id):
    source = Source.query.get_or_404(source_id)
    db.session.delete(source)
    db.session.commit()
    return jsonify({'deleted': source_id})


# ---------------------------------------------------------------- listening

@api_bp.post('/ingest')
def ingest():
    brand, error = _require_brand()
    if error:
        return error
    result = run_ingestion(brand, current_app.config)
    result['alerts'] = [a.to_dict() for a in evaluate_alerts(brand, utcnow())]
    return jsonify(result)


@api_bp.post('/seed')
def seed():
    brand, error = _require_brand()
    if error:
        return error
    data = payload()
    days = min(int(data.get('days', 30) or 30), MAX_SEED_DAYS)
    per_day = min(int(data.get('per_day', 6) or 6), 40)
    result = run_seed(brand, utcnow(), days=days, per_day=per_day)
    result['alerts'] = [a.to_dict() for a in evaluate_alerts(brand, utcnow())]
    return jsonify(result)


@api_bp.get('/mentions')
def list_mentions():
    brand, error = _require_brand()
    if error:
        return error
    limit = min(request.args.get('limit', 50, type=int), 200)
    rows = (
        Mention.query.filter(Mention.brand_id == brand.id)
        .order_by(Mention.published_at.desc()).limit(limit).all()
    )
    return jsonify({'mentions': [m.to_dict() for m in rows]})


@api_bp.get('/topics')
def topics():
    brand, error = _require_brand()
    if error:
        return error
    return jsonify({'topics': pick_topics(brand, utcnow(), limit=12)})


@api_bp.post('/alerts/<int:alert_id>/read')
def read_alert(alert_id):
    alert = Alert.query.get_or_404(alert_id)
    alert.is_read = True
    db.session.commit()
    return jsonify(alert.to_dict())


# ---------------------------------------------------------------- content

@api_bp.post('/generate')
def generate():
    brand, error = _require_brand()
    if error:
        return error
    data = payload()
    channels = data.get('channels') or ['linkedin', 'x']
    if isinstance(channels, str):
        channels = [c.strip() for c in channels.split(',') if c.strip()]
    invalid = [c for c in channels if c not in CHANNELS]
    if invalid:
        return jsonify({'error': f'unknown channel(s): {", ".join(invalid)}'}), 400

    result = generate_drafts(
        brand, current_app.config,
        topic=(data.get('topic') or '').strip() or None,
        channels=channels,
        count=min(int(data.get('count', 1) or 1), 5),
    )
    return jsonify(result)


@api_bp.patch('/posts/<int:post_id>')
def update_post(post_id):
    post = Post.query.get_or_404(post_id)
    data = payload()
    if 'body' in data:
        post.body = (data['body'] or '').strip()
    if 'hashtags' in data:
        tags = data['hashtags']
        post.hashtags = ' '.join(tags) if isinstance(tags, list) else str(tags)
    if 'channel' in data and data['channel'] in CHANNELS:
        post.channel = data['channel']
    if 'scheduled_for' in data and data['scheduled_for']:
        from datetime import datetime
        try:
            post.scheduled_for = datetime.fromisoformat(data['scheduled_for'])
        except ValueError:
            return jsonify({'error': 'scheduled_for must be ISO 8601'}), 400
    db.session.commit()
    return jsonify(post.to_dict())


@api_bp.post('/posts/<int:post_id>/approve')
def approve_post(post_id):
    post = Post.query.get_or_404(post_id)
    data = payload()
    scheduled_for = None
    if data.get('scheduled_for'):
        from datetime import datetime
        try:
            scheduled_for = datetime.fromisoformat(data['scheduled_for'])
        except ValueError:
            return jsonify({'error': 'scheduled_for must be ISO 8601'}), 400
    approve(post, utcnow(), scheduled_for)
    return jsonify(post.to_dict())


@api_bp.post('/posts/<int:post_id>/reject')
def reject_post(post_id):
    post = Post.query.get_or_404(post_id)
    reject(post)
    return jsonify(post.to_dict())


@api_bp.post('/posts/<int:post_id>/publish')
def publish_post(post_id):
    post = Post.query.get_or_404(post_id)
    brand = Brand.query.get_or_404(post.brand_id)
    result = publish_now(post, brand, current_app.config, utcnow())
    return jsonify({**result, 'post': post.to_dict()})


@api_bp.delete('/posts/<int:post_id>')
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    return jsonify({'deleted': post_id})


@api_bp.post('/scheduler/run')
def scheduler_run():
    """Publish due posts and refresh metrics. Safe to call from cron."""
    brand, error = _require_brand()
    if error:
        return error
    return jsonify(run_due(brand, current_app.config, utcnow()))
