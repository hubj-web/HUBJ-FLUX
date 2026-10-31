# -*- coding: utf-8 -*-
"""Categorizar em massa as compras do cartão: os fornecedores que mais pesam, de uma vez, com a categoria já sugerida."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import categorizacao_db as cdb
import db
from auth import login_required, requer_organizacao, requer_papel
from categorias_cartao import sugerir_categoria

categ_bp = Blueprint("categ", __name__, url_prefix="/cartao/categorizar")
TAMANHOS = (20, 40, 80)
LIMITE_POR_ENVIO = 100


def _brl(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _id_por_nome(categorias, nome):
    return next((c["id"] for c in categorias if nome and c["nome"].lower() == nome.lower()), None)


@categ_bp.route("/")
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def index():
    org = g.usuario_atual["organizacao_id"]
    n = int(request.args["n"]) if request.args.get("n", "").isdigit() and int(request.args["n"]) in TAMANHOS else 40
    cob = cdb.cobertura(org)
    cats = db.listar_categorias(org, tipo="despesa")
    linhas, acumulado = [], 0.0
    for r in db.fornecedores_sem_categoria(org, n):
        acumulado += float(r["total"])
        linhas.append({"fornecedor": r["fornecedor"], "n": r["n"], "total": float(r["total"]), "acumulado_pct": round(acumulado / cob["sem"] * 100, 1) if cob["sem"] else 0.0,
                       "sugerida": _id_por_nome(cats, sugerir_categoria(r["fornecedor"]))})
    return render_template("cartao_categorizar.html", cob=cob, linhas=linhas, categorias=cats, n=n, tamanhos=TAMANHOS, cobertura_lista=linhas[-1]["acumulado_pct"] if linhas else 0.0)


@categ_bp.route("/aplicar", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def aplicar():
    org = g.usuario_atual["organizacao_id"]
    validas = {c["id"] for c in db.listar_categorias(org, tipo="despesa")}
    pares = list(zip(request.form.getlist("forn"), request.form.getlist("cat")))[:LIMITE_POR_ENVIO]
    feitos, compras, valor, invalidas, vistos = 0, 0, 0.0, 0, set()
    for chave, cat in pares:
        chave = (chave or "").strip().upper()[:200]
        if not chave or not cat or chave in vistos:
            continue
        vistos.add(chave)
        if not cat.isdigit() or int(cat) not in validas:
            invalidas += 1
            continue
        db.criar_regra_fornecedor(org, chave, chave.title()[:200], int(cat))   # as próximas faturas já seguem a regra
        n, v = cdb.aplicar_por_chave(org, chave, int(cat))
        feitos, compras, valor = feitos + 1, compras + n, valor + v
    cob = cdb.cobertura(org)
    if invalidas:
        flash(f"{invalidas} categoria(s) escolhida(s) não valem para despesa e foram ignoradas.", "erro")
    if feitos:
        falta = f"Ainda faltam R$ {_brl(cob['sem'])} ({str(cob['pct_sem']).replace('.', ',')}% do cartão) sem categoria." if cob["sem"] else "Todas as compras do cartão estão categorizadas. 🎉"
        flash(f"{feitos} fornecedor(es) categorizado(s): {compras} compra(s) ajustada(s), R$ {_brl(valor)}. As próximas faturas já seguem essas regras. {falta}", "ok")
    elif not invalidas:
        flash("Escolha a categoria de pelo menos um fornecedor.", "erro")
    return redirect(url_for("categ.index"))
