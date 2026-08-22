# -*- coding: utf-8 -*-
from datetime import timedelta
from flask import Flask

from config import Config
import db
from auth import auth_bp, init_oauth
from inicio import inicio_bp
from admin import admin_bp
from lancamentos import lanc_bp
from cartao import cartao_bp
from planejamento import plan_bp
from controle import controle_bp
from configuracoes import config_bp
from metas import metas_bp
from relatorios import relatorios_bp
from setup import setup_bp


def fmt_brl(v):
    """Formata número no padrão brasileiro: 14000.0 -> '14.000,00'."""
    if v is None or v == "":
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def create_app():
    app = Flask(__name__)
    app.secret_key = Config.SESSION_SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=Config.APP_BASE_URL.startswith("https"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    app.jinja_env.filters["brl"] = fmt_brl

    init_oauth(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(inicio_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(lanc_bp)
    app.register_blueprint(cartao_bp)
    app.register_blueprint(plan_bp)
    app.register_blueprint(controle_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(metas_bp)
    app.register_blueprint(relatorios_bp)
    app.register_blueprint(setup_bp)

    app.teardown_appcontext(db.close_conn)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
