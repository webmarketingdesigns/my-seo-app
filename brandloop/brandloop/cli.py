"""Flask CLI commands — the same operations the API exposes, for cron and shells."""
import click
from flask.cli import with_appcontext

from .analysis.alerts import evaluate_alerts
from .generate.brandvoice import analyse_site
from .generate.composer import generate_drafts
from .ingest.pipeline import run_ingestion, run_seed
from .models import Brand, db, utcnow
from .scheduler import run_due


def _brand(brand_id=None):
    brand = Brand.query.get(brand_id) if brand_id else Brand.query.first()
    if brand is None:
        raise click.ClickException('No brand found. Create one in Settings first.')
    return brand


def register_cli(app):
    @app.cli.command('ingest')
    @click.option('--brand-id', type=int, default=None)
    @with_appcontext
    def ingest_command(brand_id):
        """Poll every enabled source for a brand."""
        brand = _brand(brand_id)
        result = run_ingestion(brand, app.config)
        click.echo(f"{brand.name}: stored {result['stored']}, skipped {result['skipped']}, "
                   f"dupes {result['duplicate']}")
        for error in result['errors']:
            click.echo(f'  ! {error}', err=True)
        alerts = evaluate_alerts(brand, utcnow())
        for alert in alerts:
            click.echo(f'  [{alert.severity}] {alert.message}')

    @app.cli.command('seed')
    @click.option('--brand-id', type=int, default=None)
    @click.option('--days', type=int, default=30)
    @click.option('--per-day', type=int, default=6)
    @with_appcontext
    def seed_command(brand_id, days, per_day):
        """Fill a brand with synthetic demo chatter."""
        brand = _brand(brand_id)
        result = run_seed(brand, utcnow(), days=days, per_day=per_day)
        click.echo(f"{brand.name}: seeded {result['stored']} mentions")

    @app.cli.command('generate')
    @click.option('--brand-id', type=int, default=None)
    @click.option('--count', type=int, default=2)
    @click.option('--channel', 'channels', multiple=True, default=('linkedin', 'x'))
    @with_appcontext
    def generate_command(brand_id, count, channels):
        """Draft posts from the current trending topics."""
        brand = _brand(brand_id)
        result = generate_drafts(brand, app.config, count=count, channels=list(channels))
        click.echo(f"{brand.name}: {result['created']} drafts via {result['generator']} "
                   f"({', '.join(result['topics']) or 'no topics'})")

    @app.cli.command('run-due')
    @click.option('--brand-id', type=int, default=None)
    @with_appcontext
    def run_due_command(brand_id):
        """Publish scheduled posts that are due and refresh metrics."""
        brand = _brand(brand_id)
        result = run_due(brand, app.config)
        click.echo(f"{brand.name}: published {result['published']}, "
                   f"metrics refreshed {result['metrics_refreshed']}")

    @app.cli.command('rescore')
    @click.option('--brand-id', type=int, default=None)
    @with_appcontext
    def rescore_command(brand_id):
        """Re-run sentiment over stored mentions (use after a lexicon change)."""
        from .analysis.sentiment import label_for, score_text
        from .models import Mention

        brand = _brand(brand_id)
        rows = Mention.query.filter(Mention.brand_id == brand.id).all()
        changed = 0
        for m in rows:
            title, content = (m.title or '').strip(), (m.content or '').strip()
            text = content if title and title.lower() in content.lower() else f'{title}. {content}'
            score = score_text(text)
            if abs(score - (m.sentiment_score or 0.0)) > 1e-6:
                m.sentiment_score, m.sentiment_label = score, label_for(score)
                changed += 1
        db.session.commit()
        click.echo(f'{brand.name}: rescored {changed} of {len(rows)} mentions')

    @app.cli.command('analyse-site')
    @click.option('--brand-id', type=int, default=None)
    @with_appcontext
    def analyse_site_command(brand_id):
        """Re-derive the brand voice profile from the brand's website."""
        brand = _brand(brand_id)
        brand.voice = analyse_site(brand.website, app.config, brand.name)
        db.session.commit()
        click.echo(f'{brand.name}: {brand.voice}')
