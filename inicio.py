# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, g, request

import db
import empresa as empresa_mod
import alertas
from auth import login_required
import regras_negocio

inicio_bp = Blueprint("inicio", __name__)


@inicio_bp.route("/")
@login_required
def index():
    usuario = g.usuario_atual
    organizacao = db.buscar_organizacao(usuario["organizacao_id"])

    if usuario["organizacao_id"] is None:
        return render_template("inicio_super_admin.html", usuario=usuario)

    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    ref_date = date.fromisoformat(mes_referencia + "-01")
    mes_anterior = (ref_date - relativedelta(months=1)).strftime("%Y-%m")
    mes_seguinte = (ref_date + relativedelta(months=1)).strftime("%Y-%m")

    alertas.disparar_lembretes(usuario["organizacao_id"])  # idempotente: não repete no mesmo dia
    totais = db.totais_mes(usuario["organizacao_id"], mes_referencia)
    ultimos = db.ultimos_lancamentos(usuario["organizacao_id"], limite=5)
    frase_saldo = regras_negocio.frase_saldo_mes(totais["saldo"])
    prefs = db.buscar_preferencias(usuario["organizacao_id"])
    setup_concluido = bool(prefs and prefs.get("setup_concluido"))
    reservado_metas = db.total_reservado_metas(usuario["organizacao_id"])
    saldo_livre = totais["saldo"] - reservado_metas
    acertos_empresas = []
    if prefs and prefs.get("modulo_empresa"):
        nomes = {e["id"]: e["nome"] for e in db.listar_empresas(usuario["organizacao_id"], apenas_ativas=False)}
        consolidado = empresa_mod.consolidar(db.acerto_itens(usuario["organizacao_id"]), db.listar_acertos(usuario["organizacao_id"]), nomes)
        acertos_empresas = [s for s in consolidado.values() if abs(s["saldo"]) >= 0.005]

    return render_template(
        "inicio.html", usuario=usuario, organizacao=organizacao,
        mes_referencia=mes_referencia, mes_anterior=mes_anterior, mes_seguinte=mes_seguinte,
        totais=totais, ultimos=ultimos, frase_saldo=frase_saldo, setup_concluido=setup_concluido,
        reservado_metas=reservado_metas, saldo_livre=saldo_livre, acertos_empresas=acertos_empresas,
    )
