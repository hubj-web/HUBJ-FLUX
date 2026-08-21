# -*- coding: utf-8 -*-
"""
Autenticação em duas camadas:

  Camada 1 (identidade) — resolvida pelo próprio Google OAuth: se o token
  veio assinado pelo Google, sabemos quem a pessoa é.

  Camada 2 (autorização) — resolvida por nós: esse e-mail está cadastrado
  na tabela `usuarios` e com status 'ativo' (ou 'pendente', ainda no
  onboarding)? Isso é checado não só no login, mas em TODA requisição
  autenticada (decorator `login_required` abaixo), para que bloquear
  alguém tenha efeito imediato, sem esperar a sessão expirar.
"""
from functools import wraps
from flask import Blueprint, redirect, url_for, session, request, g, flash
from authlib.integrations.flask_client import OAuth

from config import Config
import db

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()


def init_oauth(app):
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@auth_bp.route("/login")
def login():
    redirect_uri = Config.APP_BASE_URL.rstrip("/") + url_for("auth.callback")
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/callback")
def callback():
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.parse_id_token(token)
    email = (userinfo.get("email") or "").strip().lower()
    google_sub = userinfo.get("sub")
    nome = userinfo.get("name")

    if not email or not userinfo.get("email_verified", True):
        flash("Não foi possível confirmar seu e-mail com o Google.", "erro")
        return redirect(url_for("auth.login_page"))

    usuario = db.buscar_usuario_por_email(email)

    # Super Admin: provisionado automaticamente no primeiro login, desde que
    # o e-mail bata exatamente com o configurado em SUPER_ADMIN_EMAIL.
    if usuario is None and email == Config.SUPER_ADMIN_EMAIL:
        usuario = db.criar_super_admin(email)

    # Camada 2: sem cadastro correspondente -> acesso negado, mesmo que a
    # identidade Google seja legítima.
    if usuario is None:
        flash("Esse e-mail não está autorizado a acessar o HUB-J FLUX. "
              "Peça um convite ao administrador da sua organização.", "erro")
        return redirect(url_for("auth.login_page"))

    if usuario["status"] == "bloqueado":
        flash("Seu acesso foi bloqueado. Fale com o administrador da sua organização.", "erro")
        return redirect(url_for("auth.login_page"))

    # Primeiro login bem-sucedido de um usuário convidado: sai de "pendente"
    # e vira "ativo" de verdade, já que a pessoa está usando o sistema.
    if usuario["status"] == "pendente":
        db.ativar_usuario_se_pendente(usuario["id"])

    db.atualizar_login(usuario["id"], google_sub, nome)

    session.clear()
    session["usuario_id"] = usuario["id"]
    session.permanent = True

    return redirect(url_for("inicio.index"))


@auth_bp.route("/login-page")
def login_page():
    from flask import render_template
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


def login_required(f):
    """Carrega o usuário atual a partir do banco a CADA requisição — nunca
    confia só no que está no cookie de sessão (isso é a revalidação da
    Camada 2 em toda chamada, não só no login)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        usuario_id = session.get("usuario_id")
        if not usuario_id:
            return redirect(url_for("auth.login_page"))

        usuario = db.query_one("SELECT * FROM usuarios WHERE id = %s", (usuario_id,))
        if usuario is None or usuario["status"] == "bloqueado":
            session.clear()
            flash("Sua sessão não é mais válida. Faça login novamente.", "erro")
            return redirect(url_for("auth.login_page"))

        g.usuario_atual = usuario
        return f(*args, **kwargs)
    return wrapper


def requer_papel(*papeis_permitidos):
    """Restringe uma rota a determinados papéis (ex: só super_admin, ou
    super_admin + admin_cliente). Use sempre junto com @login_required."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if g.usuario_atual["papel"] not in papeis_permitidos:
                return "Acesso não permitido para o seu papel.", 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def requer_organizacao(f):
    """Bloqueia rotas que só fazem sentido dentro de uma organização (ex:
    lançamentos, extrato) - o Super Admin não pertence a nenhuma."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.usuario_atual["organizacao_id"] is None:
            return "Esta área é específica de uma organização. O Super Admin não tem acesso direto aqui.", 403
        return f(*args, **kwargs)
    return wrapper
