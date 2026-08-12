# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, g

import db
from auth import login_required, requer_organizacao
import regras_negocio

controle_bp = Blueprint("controle", __name__, url_prefix="/controle")


def _meses_vizinhos(mes_referencia):
    ref = date.fromisoformat(mes_referencia + "-01")
    return (ref - relativedelta(months=1)).strftime("%Y-%m"), (ref + relativedelta(months=1)).strftime("%Y-%m")


@controle_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    mes_anterior, mes_seguinte = _meses_vizinhos(mes_referencia)

    planejado_por_categoria = db.listar_planejamento_mes(org_id, mes_referencia)
    realizado_por_categoria = db.realizado_por_categoria_mes(org_id, mes_referencia)
    totais = db.totais_mes(org_id, mes_referencia)

    linhas = []
    for cat in planejado_por_categoria:
        planejado = float(cat["valor_limite"])
        realizado = realizado_por_categoria.get(cat["categoria_id"], 0.0)
        estado, cor = regras_negocio.calcular_semaforo(realizado, planejado)
        linhas.append({
            "categoria_id": cat["categoria_id"], "categoria_nome": cat["categoria_nome"],
            "planejado": planejado, "realizado": realizado, "diferenca": planejado - realizado,
            "percentual": round((realizado / planejado) * 100) if planejado else None,
            "estado": estado, "cor": cor,
        })
    linhas.sort(key=lambda x: -x["realizado"])

    maior_categoria = linhas[0] if linhas and linhas[0]["realizado"] > 0 else None
    frase = None
    if maior_categoria:
        frase = regras_negocio.frase_categoria_mais_cara(
            maior_categoria["categoria_nome"], maior_categoria["realizado"], totais["despesas"])

    return render_template(
        "controle.html", linhas=linhas, totais=totais, frase=frase,
        mes_referencia=mes_referencia, mes_anterior=mes_anterior, mes_seguinte=mes_seguinte,
    )


@controle_bp.route("/categoria/<int:categoria_id>")
@login_required
@requer_organizacao
def drill_down(categoria_id):
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    lancamentos = db.lancamentos_por_categoria_mes(org_id, categoria_id, mes_referencia)
    categoria = next((c for c in db.listar_categorias(org_id, apenas_ativas=False) if c["id"] == categoria_id), None)
    return render_template(
        "controle_categoria.html", lancamentos=lancamentos,
        categoria=categoria, mes_referencia=mes_referencia,
    )
