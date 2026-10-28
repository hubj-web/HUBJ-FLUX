# -*- coding: utf-8 -*-
"""Troca de espaço: o mesmo login entra na Família ou em uma das Empresas do cliente."""
from flask import Blueprint, flash, g, redirect, request, session, url_for

import db
from auth import login_required

espacos_bp = Blueprint("espacos", __name__, url_prefix="/espaco")


@espacos_bp.route("/trocar", methods=["POST"])
@login_required
def trocar():
    try:
        alvo = int(request.form.get("espaco_id"))
    except (TypeError, ValueError):
        flash("Espaço inválido.", "erro")
        return redirect(url_for("inicio.index"))
    espaco = next((e for e in db.listar_espacos_do_usuario(g.usuario_atual["id"]) if e["id"] == alvo), None)
    if espaco is None:
        flash("Você não tem acesso a esse espaço.", "erro")
        return redirect(url_for("inicio.index"))
    session["espaco_id"] = espaco["id"]
    flash(f"Você está em: {espaco['nome']}.", "ok")
    return redirect(url_for("inicio.index"))
