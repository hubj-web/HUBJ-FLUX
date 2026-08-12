# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
from auth import login_required, requer_organizacao
import regras_negocio

plan_bp = Blueprint("plan", __name__, url_prefix="/planejamento")


def _meses_vizinhos(mes_referencia):
    ref = date.fromisoformat(mes_referencia + "-01")
    return (ref - relativedelta(months=1)).strftime("%Y-%m"), (ref + relativedelta(months=1)).strftime("%Y-%m")


@plan_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    mes_anterior, mes_seguinte = _meses_vizinhos(mes_referencia)

    categorias = db.listar_planejamento_mes(org_id, mes_referencia)
    total_planejado = sum(float(c["valor_limite"]) for c in categorias)
    prefs = db.buscar_preferencias(org_id)

    return render_template(
        "planejamento.html",
        categorias=categorias, mes_referencia=mes_referencia,
        mes_anterior=mes_anterior, mes_seguinte=mes_seguinte,
        total_planejado=total_planejado, renda_mensal=prefs["renda_mensal"] if prefs else None,
    )


@plan_bp.route("/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.form.get("mes_referencia")
    for chave, valor in request.form.items():
        if chave.startswith("limite_"):
            categoria_id = int(chave.replace("limite_", ""))
            try:
                valor_limite = float((valor or "0").replace(",", "."))
            except ValueError:
                continue
            db.salvar_planejamento_categoria(org_id, mes_referencia, categoria_id, valor_limite)
    flash("Planejamento salvo.", "ok")
    return redirect(url_for("plan.index", mes=mes_referencia))


@plan_bp.route("/copiar-mes-anterior", methods=["POST"])
@login_required
@requer_organizacao
def copiar_mes_anterior():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.form.get("mes_referencia")
    mes_anterior, _ = _meses_vizinhos(mes_referencia)
    n = db.copiar_planejamento(org_id, mes_anterior, mes_referencia)
    if n:
        flash(f"{n} categoria(s) copiada(s) de {mes_anterior}.", "ok")
    else:
        flash(f"Não havia planejamento em {mes_anterior} para copiar.", "erro")
    return redirect(url_for("plan.index", mes=mes_referencia))


@plan_bp.route("/renda", methods=["POST"])
@login_required
@requer_organizacao
def salvar_renda():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.form.get("mes_referencia")
    try:
        renda = float((request.form.get("renda_mensal") or "0").replace(",", "."))
    except ValueError:
        flash("Renda inválida.", "erro")
        return redirect(url_for("plan.index", mes=mes_referencia))
    db.salvar_renda_mensal(org_id, renda)
    flash("Renda mensal salva.", "ok")
    return redirect(url_for("plan.index", mes=mes_referencia))


@plan_bp.route("/sugestao-automatica", methods=["POST"])
@login_required
@requer_organizacao
def sugestao_automatica():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.form.get("mes_referencia")
    prefs = db.buscar_preferencias(org_id)
    if not prefs or not prefs["renda_mensal"]:
        flash("Informe a renda mensal antes de usar a sugestão automática.", "erro")
        return redirect(url_for("plan.index", mes=mes_referencia))

    sugestoes = regras_negocio.sugerir_limites_por_renda(float(prefs["renda_mensal"]))
    categorias = db.listar_categorias(org_id)
    aplicadas = 0
    for cat in categorias:
        if cat["nome"] in sugestoes:
            db.salvar_planejamento_categoria(org_id, mes_referencia, cat["id"], sugestoes[cat["nome"]])
            aplicadas += 1
    flash(f"Sugestão automática aplicada em {aplicadas} categoria(s), com base na renda informada.", "ok")
    return redirect(url_for("plan.index", mes=mes_referencia))
