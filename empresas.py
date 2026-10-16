# -*- coding: utf-8 -*-
"""Módulo Pessoa + Empresa: cadastro das empresas e o acerto entre a Família e cada uma."""
import csv
import io
import re
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, Response

import db
import empresa as empresa_mod
from auth import login_required, requer_organizacao, requer_papel

empresas_bp = Blueprint("empresas", __name__, url_prefix="/empresas")


def _org():
    return g.usuario_atual["organizacao_id"]


def _exige_modulo():
    if not db.modulo_empresa_ativo(_org()):
        abort(404)


def _brl(v):
    return f"{float(v):.2f}".replace(".", ",")


def _consolidado(org_id, empresas):
    nomes = {e["id"]: e["nome"] for e in empresas}
    return empresa_mod.consolidar([dict(i) for i in db.acerto_itens(org_id)], [dict(a) for a in db.listar_acertos(org_id)], nomes)


# ---------- cadastro das empresas (admin) ----------

@empresas_bp.route("/")
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def index():
    _exige_modulo()
    return render_template("empresas.html", empresas=db.listar_empresas(_org(), apenas_ativas=False))


@empresas_bp.route("/nova", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def nova():
    _exige_modulo()
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome da empresa.", "erro")
    elif any(e["nome"].lower() == nome.lower() for e in db.listar_empresas(_org(), apenas_ativas=False)):
        flash(f"Já existe uma empresa chamada \"{nome}\".", "erro")
    else:
        db.criar_empresa(_org(), nome)
        flash(f"Empresa \"{nome}\" criada. Agora você pode marcar compras e lançamentos como dela.", "ok")
    return redirect(url_for("empresas.index"))


@empresas_bp.route("/<int:empresa_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def salvar(empresa_id):
    _exige_modulo()
    atual = db.buscar_empresa(_org(), empresa_id)
    nome = request.form.get("nome", "").strip()
    if not atual:
        flash("Empresa não encontrada.", "erro")
    elif not nome:
        flash("Informe o nome da empresa.", "erro")
    elif any(e["id"] != empresa_id and e["nome"].lower() == nome.lower() for e in db.listar_empresas(_org(), apenas_ativas=False)):
        flash(f"Já existe uma empresa chamada \"{nome}\".", "erro")
    else:
        db.atualizar_empresa(empresa_id, _org(), nome, request.form.get("ativa") == "on")
        flash("Empresa atualizada.", "ok")
    return redirect(url_for("empresas.index"))


@empresas_bp.route("/<int:empresa_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def excluir(empresa_id):
    _exige_modulo()
    empresa = db.buscar_empresa(_org(), empresa_id)
    if not empresa:
        flash("Empresa não encontrada.", "erro")
    else:
        usos = db.empresa_em_uso(empresa_id, _org())
        if usos:
            flash(f"\"{empresa['nome']}\" tem {usos} registro(s) ligados a ela (compras, lançamentos, regras ou acertos). "
                  f"Para não perder o histórico, desative em vez de excluir.", "erro")
        else:
            db.excluir_empresa(empresa_id, _org())
            flash(f"Empresa \"{empresa['nome']}\" excluída.", "ok")
    return redirect(url_for("empresas.index"))


# ---------- acerto Família x empresa ----------

@empresas_bp.route("/acerto")
@login_required
@requer_organizacao
def acerto():
    _exige_modulo()
    empresas = db.listar_empresas(_org(), apenas_ativas=False)
    if not empresas:
        return render_template("acerto.html", empresas=[], sel=None, grupos=[], hoje=date.today().isoformat())
    ids = {e["id"] for e in empresas}
    try:
        eid = int(request.args.get("empresa_id") or empresas[0]["id"])
    except ValueError:
        eid = empresas[0]["id"]
    if eid not in ids:
        eid = empresas[0]["id"]
    consolidado = _consolidado(_org(), empresas)
    sel = consolidado[eid]
    por_mes = {}
    for it in sel["itens"]:
        por_mes.setdefault(it["mes"], []).append(it)
    grupos = [{"mes": mes, "saldo": saldo, "itens": por_mes.get(mes, [])} for mes, saldo in sel["meses"].items()]
    return render_template("acerto.html", empresas=empresas, sel=sel, grupos=grupos, hoje=date.today().isoformat(),
                           saldos={e["id"]: consolidado[e["id"]]["saldo"] for e in empresas})


@empresas_bp.route("/acerto/novo", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def novo_acerto():
    _exige_modulo()
    ids = {e["id"] for e in db.listar_empresas(_org(), apenas_ativas=False)}
    try:
        empresa_id = int(request.form.get("empresa_id"))
        valor = float((request.form.get("valor") or "").replace(".", "").replace(",", "."))
        data = date.fromisoformat(request.form.get("data") or "")
    except (TypeError, ValueError):
        flash("Informe a data e um valor válido.", "erro")
        return redirect(url_for("empresas.acerto"))
    sentido = request.form.get("sentido")
    if empresa_id not in ids or valor <= 0 or sentido not in ("empresa_paga", "familia_paga"):
        flash("Dados do acerto inválidos.", "erro")
        return redirect(url_for("empresas.acerto"))
    db.criar_acerto(_org(), empresa_id, data, round(valor, 2), sentido, (request.form.get("descricao") or "").strip()[:250] or None)
    flash("Acerto registrado.", "ok")
    return redirect(url_for("empresas.acerto", empresa_id=empresa_id))


@empresas_bp.route("/acerto/<int:acerto_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def excluir_acerto(acerto_id):
    _exige_modulo()
    db.excluir_acerto(acerto_id, _org())
    flash("Acerto removido: o saldo voltou a contar esse valor.", "ok")
    try:
        return redirect(url_for("empresas.acerto", empresa_id=int(request.form.get("empresa_id"))))
    except (TypeError, ValueError):
        return redirect(url_for("empresas.acerto"))


@empresas_bp.route("/acerto.csv")
@login_required
@requer_organizacao
def acerto_csv():
    _exige_modulo()
    empresas = db.listar_empresas(_org(), apenas_ativas=False)
    por_id = {e["id"]: e for e in empresas}
    try:
        eid = int(request.args.get("empresa_id"))
    except (TypeError, ValueError):
        eid = None
    if eid not in por_id:
        abort(404)
    sel = _consolidado(_org(), empresas)[eid]
    nome = sel["nome"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([f"Acerto Família × {nome}"])
    w.writerow(["Saldo", _brl(sel["saldo"]), sel["frase"]])
    w.writerow([])
    w.writerow(["Mês", "Data", "Origem", "Descrição", "Quem pagou", "Para quem foi", "Valor", "Efeito no saldo"])
    for it in sorted(sel["itens"], key=lambda i: (i["mes"], str(i.get("data") or ""))):
        pagou, foi = ("Família", nome) if it["efeito"] > 0 else (nome, "Família")
        w.writerow([it["mes"], it.get("data") or "", "cartão" if it["origem"] == "cartao" else "lançamento", it.get("descricao") or "",
                    pagou, foi, _brl(it["valor"]), _brl(it["efeito"])])
    w.writerow([])
    w.writerow(["Acertos registrados"])
    w.writerow(["Data", "Quem pagou", "Valor", "Observação"])
    for a in sorted(sel["acertos"], key=lambda a: str(a["data"])):
        w.writerow([a["data"], nome if a["sentido"] == "empresa_paga" else "Família", _brl(a["valor"]), a.get("descricao") or ""])
    slug = re.sub(r"[^A-Za-z0-9]+", "-", nome).strip("-").lower() or "empresa"
    return Response(buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="acerto_{slug}.csv"'})
