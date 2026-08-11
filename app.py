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


def create_app():
    app = Flask(__name__)
    app.secret_key = Config.SESSION_SECRET_KEY

    # cookies de sessão seguros (parte da Camada 2 de autenticação: o
    # cookie só é assinado/confiável, nunca guarda dado sensível em claro)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=Config.APP_BASE_URL.startswith("https"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )

    init_oauth(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(inicio_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(lanc_bp)
    app.register_blueprint(cartao_bp)

    app.teardown_appcontext(db.close_conn)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
