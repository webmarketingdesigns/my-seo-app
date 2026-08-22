"""Server-rendered pages."""
from datetime import timedelta

from flask import Blueprint, render_template

from ..analysis import metrics as metrics_mod
from ..analysis.topics import trending_terms
from ..models import Alert, CHANNELS, Mention, Post, db, utcnow
from .common import all_brands, current_brand

views_bp = Blueprint('views', __name__)

MENTIONS_PER_PAGE = 40


def _shell(brand, **extra):
    """Context every page needs: the brand switcher and the unread alert count."""
    unread = (
        Alert.query.filter(Alert.brand_id == brand.id, Alert.is_read.is_(False)).count()
        if brand else 0
    )
    return {'brand': brand, 'brands': all_brands(), 'unread_alerts': unread, **extra}


@views_bp.route('/')
def dashboard():
    brand = current_brand()
    if brand is None:
        return render_template('empty.html', **_shell(None))

    now = utcnow()
    data = metrics_mod.brand_dashboard(brand.id, now, days=7)
    mentions = data.pop('mentions_all')
    own = [m for m in mentions if not m.is_competitor]

    alerts = (
        Alert.query.filter(Alert.brand_id == brand.id)
        .order_by(Alert.created_at.desc()).limit(6).all()
    )
    recent = sorted(own, key=lambda m: m.published_at, reverse=True)[:8]
    topics = trending_terms(mentions, now, window_hours=168, top_n=6,
                            ignore=set(brand.name.lower().split()))

    return render_template(
        'dashboard.html',
        **_shell(
            brand,
            kpis=data,
            volume=metrics_mod.volume_series(own, now, days=14),
            sentiment=metrics_mod.sentiment_series(own, now, days=14),
            share=metrics_mod.share_of_voice(mentions),
            alerts=alerts,
            recent=recent,
            topics=topics,
            queue=Post.query.filter(Post.brand_id == brand.id, Post.status == 'draft')
                            .order_by(Post.created_at.desc()).limit(3).all(),
        ),
    )


@views_bp.route('/mentions')
def mentions():
    from flask import request

    brand = current_brand()
    if brand is None:
        return render_template('empty.html', **_shell(None))

    query = Mention.query.filter(Mention.brand_id == brand.id)

    sentiment = request.args.get('sentiment', '')
    source = request.args.get('source', '')
    scope = request.args.get('scope', 'brand')
    search = (request.args.get('q') or '').strip()

    if sentiment in ('positive', 'neutral', 'negative'):
        query = query.filter(Mention.sentiment_label == sentiment)
    if source:
        query = query.filter(Mention.source_kind == source)
    if scope == 'brand':
        query = query.filter(Mention.is_competitor.is_(False))
    elif scope == 'competitor':
        query = query.filter(Mention.is_competitor.is_(True))
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Mention.title.ilike(like), Mention.content.ilike(like)))

    page = max(request.args.get('page', 1, type=int), 1)
    rows = (
        query.order_by(Mention.published_at.desc())
        .limit(MENTIONS_PER_PAGE + 1).offset((page - 1) * MENTIONS_PER_PAGE).all()
    )
    has_next = len(rows) > MENTIONS_PER_PAGE

    sources = [
        row[0] for row in
        db.session.query(Mention.source_kind).filter(Mention.brand_id == brand.id).distinct().all()
    ]

    return render_template(
        'mentions.html',
        **_shell(
            brand, mentions=rows[:MENTIONS_PER_PAGE], page=page, has_next=has_next,
            sources=sorted(sources),
            filters={'sentiment': sentiment, 'source': source, 'scope': scope, 'q': search},
        ),
    )


@views_bp.route('/insights')
def insights():
    brand = current_brand()
    if brand is None:
        return render_template('empty.html', **_shell(None))

    now = utcnow()
    mentions = Mention.query.filter(
        Mention.brand_id == brand.id, Mention.published_at >= now - timedelta(days=60)
    ).all()
    own = [m for m in mentions if not m.is_competitor]

    top_authors = {}
    for m in own:
        if not m.author:
            continue
        row = top_authors.setdefault(m.author, {'author': m.author, 'mentions': 0, 'reach': 0,
                                                'sentiment': 0.0})
        row['mentions'] += 1
        row['reach'] += m.reach or 0
        row['sentiment'] += m.sentiment_score or 0.0
    voices = sorted(top_authors.values(), key=lambda r: r['reach'], reverse=True)[:8]
    for row in voices:
        row['sentiment'] = round(row['sentiment'] / row['mentions'], 2)

    return render_template(
        'insights.html',
        **_shell(
            brand,
            topics=trending_terms(mentions, now, window_hours=168, top_n=14,
                                  ignore=set(brand.name.lower().split())),
            share=metrics_mod.share_of_voice(mentions),
            sources=metrics_mod.source_breakdown(own),
            sentiment=metrics_mod.sentiment_series(own, now, days=30),
            volume=metrics_mod.volume_series(own, now, days=30),
            voices=voices,
        ),
    )


@views_bp.route('/studio')
def studio():
    brand = current_brand()
    if brand is None:
        return render_template('empty.html', **_shell(None))

    from ..generate.composer import pick_topics

    now = utcnow()
    drafts = (
        Post.query.filter(Post.brand_id == brand.id, Post.status == 'draft')
        .order_by(Post.created_at.desc()).all()
    )
    return render_template(
        'studio.html',
        **_shell(
            brand, drafts=drafts, topics=pick_topics(brand, now, limit=8),
            channels=CHANNELS,
            rejected=Post.query.filter(Post.brand_id == brand.id, Post.status == 'rejected')
                                .order_by(Post.created_at.desc()).limit(5).all(),
        ),
    )


@views_bp.route('/calendar')
def calendar():
    brand = current_brand()
    if brand is None:
        return render_template('empty.html', **_shell(None))

    now = utcnow()
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=28)

    posts = Post.query.filter(
        Post.brand_id == brand.id,
        Post.status.in_(('scheduled', 'published')),
        Post.scheduled_for.isnot(None),
        Post.scheduled_for >= start,
        Post.scheduled_for < end,
    ).order_by(Post.scheduled_for).all()

    by_day = {}
    for post in posts:
        by_day.setdefault(post.scheduled_for.date(), []).append(post)

    weeks = []
    for week in range(4):
        days = []
        for offset in range(7):
            day = (start + timedelta(days=week * 7 + offset)).date()
            days.append({'date': day, 'posts': by_day.get(day, []), 'is_today': day == now.date()})
        weeks.append(days)

    return render_template('calendar.html', **_shell(brand, weeks=weeks, total=len(posts)))


@views_bp.route('/analytics')
def analytics():
    brand = current_brand()
    if brand is None:
        return render_template('empty.html', **_shell(None))

    posts = (
        Post.query.filter(Post.brand_id == brand.id, Post.status == 'published')
        .order_by(Post.published_at.desc()).all()
    )
    rows = []
    for post in posts:
        metric = post.latest_metric
        rows.append({'post': post, 'metric': metric,
                     'engagements': metric.engagements if metric else 0,
                     'rate': metric.engagement_rate if metric else 0.0})
    top = sorted(rows, key=lambda r: r['rate'], reverse=True)[:5]

    return render_template(
        'analytics.html',
        **_shell(
            brand, rows=rows, top=top,
            channels=metrics_mod.channel_performance(brand.id),
            totals={
                'posts': len(rows),
                'impressions': sum(r['metric'].impressions if r['metric'] else 0 for r in rows),
                'engagements': sum(r['engagements'] for r in rows),
            },
        ),
    )


@views_bp.route('/settings')
def settings():
    brand = current_brand()
    return render_template(
        'settings.html',
        **_shell(brand, source_kinds=('rss', 'hackernews', 'reddit')),
    )
