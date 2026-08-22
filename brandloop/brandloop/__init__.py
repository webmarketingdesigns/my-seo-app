"""BrandLoop — listen, analyse, generate, publish, measure."""
from flask import Flask

from .config import Config
from .models import db

__version__ = '0.1.0'


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object(config_object)

    db.init_app(app)

    from .routes.views import views_bp
    from .routes.api import api_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    from .cli import register_cli
    register_cli(app)

    from . import filters
    filters.register(app)

    with app.app_context():
        db.create_all()
        from .bootstrap import ensure_demo_brand
        ensure_demo_brand()

    return app
