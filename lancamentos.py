# -*- coding: utf-8 -*-
import uuid
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
from auth import login_required, requer_organizacao

lanc_bp = Blueprint("lanc", __name__)


def _contexto_formulario(org_id):
    return {
        "categorias": db.listar_categorias(org_id),
        "formas_pagamento": db.listar_formas_pagamento(org_id),
        "cartoes": db.listar_cartoes(org_id),
        "pessoas": db.listar_pessoas(org_id),
    }


@lanc_bp.route("/lancamentos/novo", methods=["GET", "POST"])
@login_required
@requer_organizacao
def novo():
    org_id = g.usuario_atual["organizacao_id"]

    if request.method == "GET":
        tipo_inicial = request.args.get("tipo", "despesa")
        ctx = _contexto_formulario(org_id)
        return render_template("lancamento_form.html", tipo_inicial=tipo_inicial, hoje=date.today().isoformat(), **ctx)

    tipo = request.form.get("tipo")
    valor_str = (request.form.get("valor") or "").replace(",", ".")
    descricao = request.form.get("descricao", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    subcategoria_id = request.form.get("subcategoria_id") or None
    forma_pagamento_id = request.form.get("forma_pagamento_id") or None
    cartao_id = request.form.get("cartao_id") or None
    pessoa_id = request.form.get("pessoa_id") or None
    observacao = request.form.get("observacao", "").strip()
    data_str = request.form.get("data") or date.today().isoformat()
    parcelado = request.form.get("parcelado") == "on"
    num_parcelas = int(request.form.get("num_parcelas") or 1) if parcelado else 1

    try:
        valor_total = float(valor_str)
        data_lanc = date.fromisoformat(data_str)
    except (ValueError, TypeError):
        flash("Valor ou data inválidos.", "erro")
        return redirect(url_for("lanc.novo"))

    if tipo not in ("receita", "despesa") or valor_total <= 0:
        flash("Preencha tipo e valor corretamente.", "erro")
        return redirect(url_for("lanc.novo"))

    if not categoria_id and descricao:
        categoria_id = db.sugerir_categoria_por_descricao(org_id, descricao)

    base = {
        "tipo": tipo, "descricao": descricao, "categoria_id": categoria_id,
        "subcategoria_id": subcategoria_id, "forma_pagamento_id": forma_pagamento_id,
        "cartao_id": cartao_id, "pessoa_id": pessoa_id, "observacao": observacao,
    }

    if parcelado and num_parcelas > 1:
        grupo_id = str(uuid.uuid4())
        # Regra de arredondamento: divide igualmente e a 1ª parcela absorve
        # a diferença de centavos que sobrar (ex: R$100 em 3x -> 33,34 + 33,33 + 33,33,
        # nunca perde 1 centavo por arredondamento acumulado).
        valor_parcela = round(valor_total / num_parcelas, 2)
        diferenca_centavos = round(valor_total - (valor_parcela * num_parcelas), 2)
        for i in range(num_parcelas):
            valor_desta = valor_parcela + (diferenca_centavos if i == 0 else 0)
            db.criar_lancamento(org_id, {
                **base,
                "data": data_lanc + relativedelta(months=i),
                "valor": valor_desta,
                "grupo_parcelamento_id": grupo_id,
                "parcela_atual": i + 1,
                "parcela_total": num_parcelas,
            }, g.usuario_atual["id"])
        flash(f"Lançamento parcelado em {num_parcelas}x (1ª parcela {_fmt_moeda(valor_parcela + diferenca_centavos)}, "
              f"demais {_fmt_moeda(valor_parcela)}) criado.", "ok")
    else:
        db.criar_lancamento(org_id, {
            **base, "data": data_lanc, "valor": valor_total,
            "grupo_parcelamento_id": None, "parcela_atual": None, "parcela_total": None,
        }, g.usuario_atual["id"])
        flash("Lançamento criado com sucesso.", "ok")

    return redirect(url_for("lanc.novo", tipo=tipo))


def _fmt_moeda(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------- Extrato ----------

@lanc_bp.route("/extrato")
@login_required
@requer_organizacao
def extrato():
    org_id = g.usuario_atual["organizacao_id"]
    filtros = {
        "data_inicio": request.args.get("data_inicio") or None,
        "data_fim": request.args.get("data_fim") or None,
        "tipo": request.args.get("tipo") or None,
        "categoria_id": request.args.get("categoria_id") or None,
        "forma_pagamento_id": request.args.get("forma_pagamento_id") or None,
        "cartao_id": request.args.get("cartao_id") or None,
        "pessoa_id": request.args.get("pessoa_id") or None,
        "busca": request.args.get("busca") or None,
    }
    lancamentos = db.listar_lancamentos(org_id, filtros)
    ctx = _contexto_formulario(org_id)
    return render_template("extrato.html", lancamentos=lancamentos, filtros=filtros, **ctx)


@lanc_bp.route("/extrato/<int:lid>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir(lid):
    db.excluir_lancamento(lid, g.usuario_atual["organizacao_id"])
    flash("Lançamento excluído.", "ok")
    return redirect(url_for("lanc.extrato"))


@lanc_bp.route("/extrato/<int:lid>/duplicar", methods=["POST"])
@login_required
@requer_organizacao
def duplicar(lid):
    org_id = g.usuario_atual["organizacao_id"]
    original = db.buscar_lancamento(lid, org_id)
    if not original:
        flash("Lançamento não encontrado.", "erro")
        return redirect(url_for("lanc.extrato"))
    db.criar_lancamento(org_id, {
        "data": date.today(), "tipo": original["tipo"], "valor": float(original["valor"]),
        "descricao": original["descricao"], "categoria_id": original["categoria_id"],
        "subcategoria_id": original["subcategoria_id"], "forma_pagamento_id": original["forma_pagamento_id"],
        "cartao_id": original["cartao_id"], "pessoa_id": original["pessoa_id"],
        "grupo_parcelamento_id": None, "parcela_atual": None, "parcela_total": None,
        "observacao": original["observacao"],
    }, g.usuario_atual["id"])
    flash("Lançamento duplicado com a data de hoje.", "ok")
    return redirect(url_for("lanc.extrato"))


@lanc_bp.route("/extrato/<int:lid>/editar", methods=["POST"])
@login_required
@requer_organizacao
def editar(lid):
    org_id = g.usuario_atual["organizacao_id"]
    valor_str = (request.form.get("valor") or "").replace(",", ".")
    try:
        valor = float(valor_str)
    except ValueError:
        flash("Valor inválido.", "erro")
        return redirect(url_for("lanc.extrato"))
    db.atualizar_lancamento(lid, org_id, {
        "data": request.form.get("data"),
        "tipo": request.form.get("tipo"),
        "valor": valor,
        "descricao": request.form.get("descricao", "").strip(),
        "categoria_id": request.form.get("categoria_id") or None,
        "subcategoria_id": request.form.get("subcategoria_id") or None,
        "forma_pagamento_id": request.form.get("forma_pagamento_id") or None,
        "cartao_id": request.form.get("cartao_id") or None,
        "pessoa_id": request.form.get("pessoa_id") or None,
        "observacao": request.form.get("observacao", "").strip(),
    })
    flash("Lançamento atualizado.", "ok")
    return redirect(url_for("lanc.extrato"))


# ---------- Lançamentos recorrentes ----------

@lanc_bp.route("/lancamentos/recorrentes", methods=["GET", "POST"])
@login_required
@requer_organizacao
def recorrentes():
    org_id = g.usuario_atual["organizacao_id"]

    if request.method == "POST":
        valor_str = (request.form.get("valor") or "").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            flash("Valor inválido.", "erro")
            return redirect(url_for("lanc.recorrentes"))
        db.criar_template_recorrente(org_id, {
            "nome": request.form.get("nome", "").strip(),
            "valor": valor,
            "categoria_id": request.form.get("categoria_id") or None,
            "forma_pagamento_id": request.form.get("forma_pagamento_id") or None,
            "frequencia": request.form.get("frequencia", "mensal"),
        })
        flash("Modelo recorrente criado.", "ok")
        return redirect(url_for("lanc.recorrentes"))

    templates = db.listar_templates_recorrentes(org_id)
    ctx = _contexto_formulario(org_id)
    return render_template("recorrentes.html", templates=templates, **ctx)


@lanc_bp.route("/lancamentos/recorrentes/<int:tid>/lancar", methods=["POST"])
@login_required
@requer_organizacao
def lancar_recorrente(tid):
    org_id = g.usuario_atual["organizacao_id"]
    tpl = db.buscar_template_recorrente(tid, org_id)
    if not tpl:
        flash("Modelo não encontrado.", "erro")
        return redirect(url_for("lanc.recorrentes"))
    db.criar_lancamento(org_id, {
        "data": date.today(), "tipo": "despesa", "valor": float(tpl["valor"]),
        "descricao": tpl["nome"], "categoria_id": tpl["categoria_id"], "subcategoria_id": None,
        "forma_pagamento_id": tpl["forma_pagamento_id"], "cartao_id": None, "pessoa_id": None,
        "grupo_parcelamento_id": None, "parcela_atual": None, "parcela_total": None,
        "observacao": f"Lançado a partir do modelo recorrente \"{tpl['nome']}\"",
    }, g.usuario_atual["id"])
    flash(f"\"{tpl['nome']}\" lançado hoje.", "ok")
    return redirect(url_for("lanc.recorrentes"))


@lanc_bp.route("/lancamentos/recorrentes/<int:tid>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_recorrente(tid):
    db.excluir_template_recorrente(tid, g.usuario_atual["organizacao_id"])
    flash("Modelo recorrente removido.", "ok")
    return redirect(url_for("lanc.recorrentes"))
