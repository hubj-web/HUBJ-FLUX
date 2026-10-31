# -*- coding: utf-8 -*-
"""Meu dinheiro total: o quadro inteiro do cliente (família + empresas) numa tela só. Só para quem administra os espaços."""
import re
from datetime import date

from flask import Blueprint, render_template, request, g

import cartao_analise
import consolidado_logica as cl
import db
import financeiro_db as fdb
import transferencias_db as tdb
import transferencias_logica as tl
from auth import login_required, requer_organizacao, requer_papel
from modulos import requer_modulo
from transferencias import _espacos_admin

consol_bp = Blueprint("consol", __name__, url_prefix="/consolidado")
MODULO = "consolidado"


@consol_bp.route("/")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def index():
    cliente, familias, empresas = _espacos_admin()
    espacos = familias + empresas
    mes = request.args.get("mes") if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", request.args.get("mes") or "") else date.today().strftime("%Y-%m")
    ctx = dict(mes=mes, anterior=cartao_analise.somar_meses(mes, -1), proximo=cartao_analise.somar_meses(mes, 1), rotulo=cartao_analise.rotulo_mes, operacoes=tl.OPERACOES)
    if len(espacos) < 2:
        return render_template("consolidado.html", **ctx, c=None)
    linhas = []
    for e in espacos:
        t = db.totais_mes(e["id"], mes)
        linhas.append({"id": e["id"], "nome": e["nome"], "tipo": e["tipo"], "receitas": t["receitas"], "despesas": t["despesas"], "saldo": t["saldo"],
                       "saldo_contas": fdb.saldo_das_contas(e["id"])[0]})
    ids = [e["id"] for e in espacos]
    c = cl.consolidar(linhas, tdb.listar_transferencias(cliente, ids, mes))
    emprestimo = tl.resumo(tdb.listar_transferencias(cliente, ids))["emprestimo_em_aberto"]
    return render_template("consolidado.html", **ctx, c=c, emprestimo=emprestimo)
