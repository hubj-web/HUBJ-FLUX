# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, g

import db
from auth import login_required

inicio_bp = Blueprint("inicio", __name__)


@inicio_bp.route("/")
@login_required
def index():
    usuario = g.usuario_atual
    organizacao = db.buscar_organizacao(usuario["organizacao_id"])
    return render_template("inicio.html", usuario=usuario, organizacao=organizacao)
