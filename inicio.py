# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, g, request

import db
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

    totais = db.totais_mes(usuario["organizacao_id"], mes_referencia)
    ultimos = db.ultimos_lancamentos(usuario["organizacao_id"], limite=5)
    frase_saldo = regras_negocio.frase_saldo_mes(totais["saldo"])

    return render_template(
        "inicio.html", usuario=usuario, organizacao=organizacao,
        mes_referencia=mes_referencia, mes_anterior=mes_anterior, mes_seguinte=mes_seguinte,
        totais=totais, ultimos=ultimos, frase_saldo=frase_saldo,
    )
