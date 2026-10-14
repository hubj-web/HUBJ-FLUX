# -*- coding: utf-8 -*-
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, g, request, url_for

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
from mais import mais_bp
from alertas import alertas_bp
import nav_catalogo


def fmt_brl(v):
    """Formata número no padrão brasileiro: 14000.0 -> '14.000,00'."""
    if v is None or v == "":
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def fmt_mes(mes):
    """'2026-02' -> 'fev/2026'."""
    try:
        return f"{MESES_ABREV[int(mes[5:7]) - 1]}/{mes[:4]}"
    except Exception:
        return mes or ""


def calc_idade(data_nasc):
    """Idade em anos a partir da data de nascimento (None se não informada)."""
    if not data_nasc:
        return None
    hoje = date.today()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))


def fmt_datahora(dt):
    """Data/hora no fuso de Brasília, ex: 05/09 14:30."""
    if not dt:
        return ""
    try:
        return dt.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m %H:%M")
    except Exception:
        return dt.strftime("%d/%m %H:%M")


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
    app.jinja_env.filters["idade"] = calc_idade
    app.jinja_env.filters["mes_label"] = fmt_mes
    app.jinja_env.filters["datahora"] = fmt_datahora

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
    app.register_blueprint(mais_bp)
    app.register_blueprint(alertas_bp)

    app.teardown_appcontext(db.close_conn)

    @app.context_processor
    def contexto_global():
        """Disponibiliza em todas as telas: atalhos da barra de baixo (escolha do
        usuário > padrão do admin > padrão do sistema) e o nº de alertas não lidos.
        Qualquer falha cai no padrão - a barra nunca pode derrubar uma tela."""
        usuario = g.get("usuario_atual")
        if not usuario or not usuario.get("organizacao_id"):
            return {}
        try:
            prefs = db.buscar_preferencias(usuario["organizacao_id"])
            chaves = nav_catalogo.resolver_chaves(usuario, prefs)
            nao_lidas = db.contar_nao_lidas(usuario["id"])
        except Exception:
            try:
                db.get_conn().rollback()
            except Exception:
                pass
            chaves, nao_lidas = list(nav_catalogo.PADRAO), 0
        itens = []
        for chave in chaves:
            icone, rotulo, endpoint, prefixos = nav_catalogo.CATALOGO[chave]
            itens.append({
                "chave": chave, "icone": icone, "rotulo": rotulo, "url": url_for(endpoint),
                "ativo": any(request.path.startswith(p) for p in prefixos),
            })
        return {"nav_atalhos": itens, "alertas_nao_lidas": nao_lidas}
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
