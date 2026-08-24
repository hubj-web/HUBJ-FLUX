# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, redirect, url_for, flash, g

import db
from auth import login_required, requer_organizacao

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


@setup_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = g.usuario_atual["organizacao_id"]
    organizacao = db.buscar_organizacao(org_id)
    checklist = db.status_checklist_setup(org_id)
    return render_template("setup.html", organizacao=organizacao, checklist=checklist)


@setup_bp.route("/concluir", methods=["POST"])
@login_required
@requer_organizacao
def concluir():
    db.marcar_setup_concluido(g.usuario_atual["organizacao_id"])
    flash("Configuração inicial concluída! Bem-vindo(a) ao HUB-J FLUX.", "ok")
    return redirect(url_for("inicio.index"))
