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
    EMAIL_REMETENTE = os.environ.get("EMAIL_REMETENTE", "HUB-J FLUX <onboarding@resend.dev>")
