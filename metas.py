# -*- coding: utf-8 -*-
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
from auth import login_required, requer_organizacao

metas_bp = Blueprint("metas", __name__, url_prefix="/metas")


def _progresso(meta):
    if not meta["valor_alvo"] or float(meta["valor_alvo"]) <= 0:
        return 0
    return min(100, round((float(meta["valor_atual"]) / float(meta["valor_alvo"])) * 100))


@metas_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = g.usuario_atual["organizacao_id"]
    metas = db.listar_metas(org_id)
    for m in metas:
        m["progresso"] = _progresso(m)
    return render_template("metas.html", metas=metas, hoje=date.today().isoformat())


@metas_bp.route("/nova", methods=["POST"])
@login_required
@requer_organizacao
def nova():
    org_id = g.usuario_atual["organizacao_id"]
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()
    valor_alvo_str = (request.form.get("valor_alvo") or "").replace(".", "").replace(",", ".")
    data_alvo = request.form.get("data_alvo") or None

    if not nome or not valor_alvo_str:
        flash("Informe ao menos o nome e o valor alvo da meta.", "erro")
        return redirect(url_for("metas.index"))
    try:
        valor_alvo = float(valor_alvo_str)
    except ValueError:
        flash("Valor alvo inválido.", "erro")
        return redirect(url_for("metas.index"))

    db.criar_meta(org_id, nome, descricao, valor_alvo, data_alvo)
    flash(f"Meta \"{nome}\" criada.", "ok")
    return redirect(url_for("metas.index"))


@metas_bp.route("/<int:meta_id>/depositar", methods=["POST"])
@login_required
@requer_organizacao
def depositar(meta_id):
    org_id = g.usuario_atual["organizacao_id"]
    valor_str = (request.form.get("valor") or "").replace(".", "").replace(",", ".")
    observacao = request.form.get("observacao", "").strip()
    try:
        valor = float(valor_str)
    except ValueError:
        flash("Valor inválido.", "erro")
        return redirect(url_for("metas.index"))

    novo_status = db.registrar_movimento_meta(meta_id, org_id, valor, observacao)
    if novo_status is None:
        flash("Meta não encontrada.", "erro")
    elif novo_status == "concluida":
        flash("🎉 Meta atingida! Parabéns.", "ok")
    else:
        flash("Valor registrado na meta.", "ok")
    return redirect(url_for("metas.index"))


@metas_bp.route("/<int:meta_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir(meta_id):
    db.excluir_meta(meta_id, g.usuario_atual["organizacao_id"])
    flash("Meta excluída.", "ok")
    return redirect(url_for("metas.index"))
