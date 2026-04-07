import os
from flask import Flask
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

from .helpers import fmt_prijs, listing_leeftijd, fmt_datum_kort


def create_app():
    load_dotenv()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.secret_key = os.environ.get("SECRET_KEY", "changeme")

    app.jinja_env.globals["fmt_prijs"] = fmt_prijs
    app.jinja_env.globals["listing_leeftijd"] = listing_leeftijd
    app.jinja_env.globals["fmt_datum_kort"] = fmt_datum_kort

    from .routes.auth import auth_bp
    from .routes.dashboard import dash_bp
    from .routes.preferences import pref_bp
    from .routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(pref_bp)
    app.register_blueprint(admin_bp)

    return app
