# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

import db
import nav_catalogo
from auth import login_required, requer_organizacao

mais_bp = Blueprint("mais", __name__)


@mais_bp.route("/mais")
@login_required
@requer_organizacao
def index():
    return render_template("mais.html")


@mais_bp.route("/mais/barra", methods=["GET", "POST"])
@login_required
@requer_organizacao
def barra():
    org_id, usuario = g.usuario_atual["organizacao_id"], g.usuario_atual
    eh_admin = usuario["papel"] in ("super_admin", "admin_cliente")

    if request.method == "POST":
        acao = request.form.get("acao")
        escolhidos = nav_catalogo.limpar([request.form.get("slot1"), request.form.get("slot2")])
        valor = ",".join(escolhidos) if escolhidos else None
        if acao == "usar_padrao":
            db.salvar_nav_usuario(usuario["id"], None)
            flash("Voltou a usar o padrão da organização.", "ok")
        elif acao == "salvar_meu":
            db.salvar_nav_usuario(usuario["id"], valor)
            flash("Sua barra de atalhos foi atualizada.", "ok")
        elif acao == "salvar_padrao_org":
            if not eh_admin:
                abort(403)
            db.salvar_nav_padrao_org(org_id, valor)
            flash("Padrão da organização atualizado (vale para quem não personalizou a própria barra).", "ok")
        else:
            flash("Não foi possível identificar a ação. Tente de novo.", "erro")
        return redirect(url_for("mais.barra"))

    prefs = db.buscar_preferencias(org_id)
    meus = nav_catalogo.limpar(usuario.get("nav_atalhos"))
    padrao_org = nav_catalogo.limpar((prefs or {}).get("nav_atalhos_padrao")) or list(nav_catalogo.PADRAO)
    return render_template("barra.html", catalogo=nav_catalogo.CATALOGO, meus=meus,
                           padrao_org=padrao_org, eh_admin=eh_admin,
                           efetivos=nav_catalogo.resolver_chaves(usuario, prefs))
