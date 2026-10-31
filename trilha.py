# -*- coding: utf-8 -*-
"""Trilha de primeiros passos: o roteiro guiado para o cliente separar e controlar o dinheiro da família e o da empresa."""
from flask import Blueprint, render_template, redirect, url_for, flash, g

import modulos
import trilha_db as tdb
import trilha_logica as tl
from auth import login_required, requer_organizacao, requer_papel
from modulos import requer_modulo

trilha_bp = Blueprint("trilha", __name__, url_prefix="/trilha")
MODULO = "trilha"


def estado(org_id):
    """A trilha deste espaço: passos, quantos estão feitos e o próximo."""
    tipo = modulos.db.query_one("SELECT tipo FROM organizacoes WHERE id = %s", (org_id,))["tipo"]
    ativos = modulos.mapa_modulos(org_id, tipo)
    lista = tl.passos(tipo, ativos, tdb.tem_empresa(org_id))
    return tl.montar(lista, tdb.feitos_auto(org_id), tdb.marcas(org_id)), tipo


@trilha_bp.route("/")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def index():
    t, tipo = estado(g.usuario_atual["organizacao_id"])
    return render_template("trilha.html", t=t, tipo=tipo)


def _passo_manual(chave):
    t, _ = estado(g.usuario_atual["organizacao_id"])
    return next((p for p in t["passos"] if p["chave"] == chave and not p["auto"]), None)


@trilha_bp.route("/<chave>/marcar", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def marcar(chave):
    if not _passo_manual(chave):
        flash("Este passo se marca sozinho quando você faz a tarefa.", "erro")
    else:
        tdb.marcar(g.usuario_atual["organizacao_id"], chave, g.usuario_atual["id"])
        flash("Passo marcado como feito.", "ok")
    return redirect(url_for("trilha.index"))


@trilha_bp.route("/<chave>/desmarcar", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def desmarcar(chave):
    if not _passo_manual(chave):
        flash("Este passo se marca sozinho quando você faz a tarefa.", "erro")
    else:
        tdb.desmarcar(g.usuario_atual["organizacao_id"], chave)
        flash("Marca retirada.", "ok")
    return redirect(url_for("trilha.index"))
