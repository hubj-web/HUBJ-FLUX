# -*- coding: utf-8 -*-
import csv
import io
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, g, Response

import db
from auth import login_required, requer_organizacao

relatorios_bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")


def _meses_vizinhos(mes_referencia):
    ref = date.fromisoformat(mes_referencia + "-01")
    return (ref - relativedelta(months=1)).strftime("%Y-%m"), (ref + relativedelta(months=1)).strftime("%Y-%m")


def _montar_relatorio(org_id, mes_referencia):
    filtros = {"data_inicio": mes_referencia + "-01"}
    ref = date.fromisoformat(mes_referencia + "-01")
    fim_mes = (ref + relativedelta(months=1)) - relativedelta(days=1)
    filtros["data_fim"] = fim_mes.isoformat()

    lancamentos = db.listar_lancamentos(org_id, filtros)
    receitas = [l for l in lancamentos if l["tipo"] == "receita"]
    despesas = [l for l in lancamentos if l["tipo"] == "despesa"]
    total_receitas = sum(float(l["valor"]) for l in receitas)
    total_despesas = sum(float(l["valor"]) for l in despesas)

    por_categoria = {}
    for l in despesas:
        nome = l["categoria_nome"] or "Sem categoria"
        por_categoria[nome] = por_categoria.get(nome, 0) + float(l["valor"])
    por_categoria_lista = sorted(
        [{"categoria": k, "valor": v} for k, v in por_categoria.items()], key=lambda x: -x["valor"])

    planejado = db.listar_planejamento_mes(org_id, mes_referencia)
    total_planejado = sum(float(c["valor_limite"]) for c in planejado)

    return {
        "receitas": receitas, "despesas": despesas,
        "total_receitas": total_receitas, "total_despesas": total_despesas,
        "saldo": total_receitas - total_despesas,
        "total_planejado": total_planejado,
        "por_categoria": por_categoria_lista,
    }


@relatorios_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    mes_anterior, mes_seguinte = _meses_vizinhos(mes_referencia)
    dados = _montar_relatorio(org_id, mes_referencia)
    return render_template(
        "relatorios.html", mes_referencia=mes_referencia, mes_anterior=mes_anterior,
        mes_seguinte=mes_seguinte, **dados,
    )


@relatorios_bp.route("/exportar.csv")
@login_required
@requer_organizacao
def exportar_csv():
    org_id = g.usuario_atual["organizacao_id"]
    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    dados = _montar_relatorio(org_id, mes_referencia)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["HUB-J FLUX — Relatório", mes_referencia])
    writer.writerow([])
    writer.writerow(["Resumo"])
    writer.writerow(["Total Receitas", f"{dados['total_receitas']:.2f}".replace(".", ",")])
    writer.writerow(["Total Despesas", f"{dados['total_despesas']:.2f}".replace(".", ",")])
    writer.writerow(["Saldo", f"{dados['saldo']:.2f}".replace(".", ",")])
    writer.writerow(["Total Planejado", f"{dados['total_planejado']:.2f}".replace(".", ",")])
    writer.writerow([])
    writer.writerow(["Despesas por categoria"])
    writer.writerow(["Categoria", "Valor"])
    for c in dados["por_categoria"]:
        writer.writerow([c["categoria"], f"{c['valor']:.2f}".replace(".", ",")])
    writer.writerow([])
    writer.writerow(["Todos os lançamentos"])
    writer.writerow(["Data", "Tipo", "Descrição", "Categoria", "Forma de pagamento", "Valor"])
    for l in sorted(dados["receitas"] + dados["despesas"], key=lambda x: x["data"]):
        writer.writerow([
            l["data"], l["tipo"], l["descricao"] or "", l["categoria_nome"] or "",
            l["forma_pagamento_nome"] or "", f"{float(l['valor']):.2f}".replace(".", ","),
        ])

    output = buffer.getvalue().encode("utf-8-sig")  # BOM para o Excel abrir acentos corretamente
    return Response(
        output, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=relatorio_{mes_referencia}.csv"},
    )
