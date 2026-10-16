# -*- coding: utf-8 -*-
"""Envio de e-mails transacionais (convites) via Resend."""
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
        json={"from": Config.EMAIL_REMETENTE, "to": [destinatario], "subject": assunto, "html": html},
        timeout=10,
    )
    if resp.status_code >= 300:
        print(f"[email_service] Falha ao enviar para {destinatario}: HTTP {resp.status_code} — {resp.text}")
    else:
        print(f"[email_service] E-mail enviado com sucesso para {destinatario}")
    return resp.status_code < 300


def _logo():
    """Logo no topo do e-mail. A imagem fica em /static do próprio app (e-mail não aceita imagem embutida)."""
    base = Config.APP_BASE_URL.rstrip("/")
    return (f'<img src="{base}/static/img/hubj-logo-email.png" width="220" alt="HUB-J Gestão e Inovação" '
            'style="display:block;border:0;margin:0 0 8px">')


def _template(email, nome_organizacao, link):
    import html as _h
    email, nome_organizacao = _h.escape(email), _h.escape(nome_organizacao)
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto">
      {_logo()}
      <h2 style="color:#3E007B;margin-top:6px">HUB-J FLUX</h2>
      <p>Olá!</p>
      <p>Você foi convidado para acessar a organização <strong>{nome_organizacao}</strong> no HUB-J FLUX.</p>
      <p>Para acessar, clique no botão abaixo e entre com a sua conta Google usando exatamente este e-mail: <strong>{email}</strong></p>
      <p style="margin:28px 0">
        <a href="{link}" style="background:#FF751F;color:#fff;padding:12px 22px;border-radius:24px;text-decoration:none;font-weight:bold">Entrar no HUB-J FLUX</a>
      </p>
      <p style="color:#8B84A0;font-size:13px">Se você não esperava este e-mail, pode ignorá-lo.</p>
    </div>
    """


def enviar_convite_admin_cliente(email, nome_organizacao):
    link = Config.APP_BASE_URL.rstrip("/") + "/login-page"
    return _enviar(email, f"Você foi convidado para {nome_organizacao} — HUB-J FLUX", _template(email, nome_organizacao, link))


def enviar_convite_membro(email, nome_organizacao):
    link = Config.APP_BASE_URL.rstrip("/") + "/login-page"
    return _enviar(email, f"Você foi convidado para {nome_organizacao} — HUB-J FLUX", _template(email, nome_organizacao, link))


def enviar_alerta(email, titulo, mensagem, link_relativo=None):
    """E-mail de alerta (ação de outra pessoa ou lembrete de vencimento)."""
    import html as _html
    link = Config.APP_BASE_URL.rstrip("/") + (link_relativo or "/alertas")
    corpo = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto">
      {_logo()}
      <h2 style="color:#3E007B;margin-top:6px">HUB-J FLUX</h2>
      <p style="font-size:16px"><strong>{_html.escape(titulo)}</strong></p>
      <p>{_html.escape(mensagem or "")}</p>
      <p style="margin:26px 0">
        <a href="{link}" style="background:#FF751F;color:#fff;padding:12px 22px;border-radius:24px;text-decoration:none;font-weight:bold">Abrir no app</a>
      </p>
      <p style="color:#8B84A0;font-size:12px">Você recebe este e-mail porque ativou esse alerta no HUB-J FLUX.</p>
    </div>
    """
    return _enviar(email, f"HUB-J FLUX · {titulo}", corpo)
