# -*- coding: utf-8 -*-
import os


class Config:
    DATABASE_URL = os.environ["DATABASE_URL"]
    GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
    SESSION_SECRET_KEY = os.environ["SESSION_SECRET_KEY"]
    SUPER_ADMIN_EMAIL = os.environ["SUPER_ADMIN_EMAIL"].strip().lower()

    # URL pública do app (usada para montar o redirect_uri do Google OAuth).
    # Em desenvolvimento local, cai no localhost; no Railway, é definida via
    # variável de ambiente APP_BASE_URL apontando para o domínio gerado.
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
