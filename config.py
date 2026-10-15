# -*- coding: utf-8 -*-
import os


class Config:
    DATABASE_URL = os.environ["DATABASE_URL"]
    GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
    SESSION_SECRET_KEY = os.environ["SESSION_SECRET_KEY"]
    SUPER_ADMIN_EMAIL = os.environ["SUPER_ADMIN_EMAIL"].strip().lower()
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
    CRON_SECRET = os.environ.get("CRON_SECRET")
    # Assistente de IA (opcional): sem a chave, o app funciona normalmente e só a IA fica indisponível
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    IA_LIMITE_24H = int(os.environ.get("IA_LIMITE_24H", "30"))  # trava de custo: chamadas por organização a cada 24h
    EMAIL_REMETENTE = os.environ.get("EMAIL_REMETENTE", "HUB-J FLUX <onboarding@resend.dev>")
