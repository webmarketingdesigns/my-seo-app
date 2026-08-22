import os


def _database_url() -> str:
    url = os.environ.get('DATABASE_URL', '')
    if url.startswith('postgres://'):
        # SQLAlchemy requires the postgresql:// scheme
        url = url.replace('postgres://', 'postgresql://', 1)
    if not url:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        url = 'sqlite:///' + os.path.join(here, 'brandloop.db')
    return url


class Config:
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-brandloop')

    # Ingestion guardrails: keep free-tier fetches polite and bounded.
    HTTP_TIMEOUT = float(os.environ.get('HTTP_TIMEOUT', '10'))
    HTTP_USER_AGENT = os.environ.get(
        'HTTP_USER_AGENT', 'BrandLoop/0.1 (+https://github.com/webmarketingdesigns/my-seo-app)'
    )
    MAX_ITEMS_PER_SOURCE = int(os.environ.get('MAX_ITEMS_PER_SOURCE', '40'))

    # Generation. Without a key the composer falls back to its template engine.
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5')
