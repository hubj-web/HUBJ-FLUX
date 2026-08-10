# -*- coding: utf-8 -*-
"""Envio de e-mails transacionais (convites) via Resend.

Se RESEND_API_KEY não estiver configurada, as funções aqui simplesmente não
enviam nada e retornam False silenciosamente — o resto do app (criar
organização, criar usuário) continua funcionando normalmente, só sem o
e-mail automático."""
import requests
from config import Config

RESEND_URL = "https://api.resend.com/emails"


def _enviar(destinatario, assunto, html):
    if not Config.RESEND_API_KEY:
        print(f"[email_service] RESEND_API_KEY não configurada — pulando envio para {destinatario}")
        return False
    resp = requests.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {Config.RESEND_API_KEY}"},
        json={
            "from": Config.EMAIL_REMETENTE,
            "to": [destinatario],
            "subject": assunto,
            "html": html,
        },
        timeout=10,
    )
    if resp.status_code >= 300:
        print(f"[email_service] Falha ao enviar para {destinatario}: HTTP {resp.status_code} — {resp.text}")
    else:
        print(f"[email_service] E-mail enviado com sucesso para {destinatario}")
    return resp.status_code < 300


def enviar_convite_admin_cliente(email, nome_organizacao):
    link = Config.APP_BASE_URL.rstrip("/") + "/login-page"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#1B2430">HUB-J FLUX</h2>
      <p>Olá!</p>
      <p>Você foi cadastrado como <strong>administrador</strong> da organização
         <strong>{nome_organizacao}</strong> no HUB-J FLUX.</p>
      <p>Para acessar, clique no botão abaixo e entre com a sua conta Google
         usando exatamente este e-mail: <strong>{email}</strong></p>
      <p style="margin:28px 0">
        <a href="{link}" style="background:#1F6F4F;color:#fff;padding:12px 22px;
           border-radius:4px;text-decoration:none;font-weight:bold">Entrar no HUB-J FLUX</a>
      </p>
      <p style="color:#6B7280;font-size:13px">Se você não esperava este e-mail, pode ignorá-lo.</p>
    </div>
    """
    return _enviar(email, f"Você foi convidado para {nome_organizacao} — HUB-J FLUX", html)


def enviar_convite_membro(email, nome_organizacao):
    link = Config.APP_BASE_URL.rstrip("/") + "/login-page"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#1B2430">HUB-J FLUX</h2>
      <p>Olá!</p>
      <p>Você foi convidado para acessar a organização
         <strong>{nome_organizacao}</strong> no HUB-J FLUX.</p>
      <p>Para acessar, clique no botão abaixo e entre com a sua conta Google
         usando exatamente este e-mail: <strong>{email}</strong></p>
      <p style="margin:28px 0">
        <a href="{link}" style="background:#1F6F4F;color:#fff;padding:12px 22px;
           border-radius:4px;text-decoration:none;font-weight:bold">Entrar no HUB-J FLUX</a>
      </p>
      <p style="color:#6B7280;font-size:13px">Se você não esperava este e-mail, pode ignorá-lo.</p>
    </div>
    """
    return _enviar(email, f"Você foi convidado para {nome_organizacao} — HUB-J FLUX", html)
