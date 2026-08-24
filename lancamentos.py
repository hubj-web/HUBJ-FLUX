# -*- coding: utf-8 -*-
import uuid
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, Response, abort

import db
from auth import login_required, requer_organizacao
import regras_negocio

lanc_bp = Blueprint("lanc", __name__)


def _contexto_formulario(org_id, tipo=None):
    return {
        "categorias": db.listar_categorias(org_id, tipo=tipo),
        "formas_pagamento": db.listar_formas_pagamento(org_id, tipo=tipo),
        "cartoes": db.listar_cartoes(org_id),
        "pessoas": db.listar_pessoas(org_id),
        "contas": db.listar_contas_bancarias(org_id),
    }


def _fmt_moeda(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@lanc_bp.route("/lancamentos/novo", methods=["GET", "POST"])
@login_required
@requer_organizacao
def novo():
    org_id = g.usuario_atual["organizacao_id"]

    if request.method == "GET":
        tipo_inicial = request.args.get("tipo", "despesa")
        ctx = _contexto_formulario(org_id, tipo=tipo_inicial)
        return render_template("lancamento_form.html", tipo_inicial=tipo_inicial, hoje=date.today().isoformat(), **ctx)

    tipo = request.form.get("tipo")
    valor_str = (request.form.get("valor") or "").replace(".", "").replace(",", ".")
    descricao = request.form.get("descricao", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    subcategoria_id = request.form.get("subcategoria_id") or None
    forma_pagamento_id = request.form.get("forma_pagamento_id") or None
    cartao_id = request.form.get("cartao_id") or None
    pessoa_id = request.form.get("pessoa_id") or None
    conta_bancaria_id = request.form.get("conta_bancaria_id") or None
    observacao = request.form.get("observacao", "").strip()
    data_str = request.form.get("data") or date.today().isoformat()
    parcelado = request.form.get("parcelado") == "on"
    num_parcelas = int(request.form.get("num_parcelas") or 1) if parcelado else 1

    # Validação: todos obrigatórios, exceto anexo e observação.
    faltando = []
    if not valor_str:
        faltando.append("Valor")
    if not descricao:
        faltando.append("Descrição")
    if not categoria_id:
        faltando.append("Categoria")
    if not forma_pagamento_id:
        faltando.append("Forma de pagamento")
    if not data_str:
        faltando.append("Data")
    if faltando:
        flash("Preencha os campos obrigatórios: " + ", ".join(faltando) + ".", "erro")
        return redirect(url_for("lanc.novo", tipo=tipo))

    modo_juros = request.form.get("modo_juros")  # 'taxa' ou 'valor_parcela'
    com_juros = parcelado and request.form.get("com_juros") == "on"
    taxa_juros_mensal = None
    valor_parcela_informado = None
    if com_juros:
        if modo_juros == "valor_parcela":
            try:
                valor_parcela_informado = float((request.form.get("valor_parcela_informado") or "0").replace(".", "").replace(",", "."))
            except ValueError:
                valor_parcela_informado = 0
            if valor_parcela_informado <= 0:
                com_juros = False
        else:
            try:
                taxa_juros_mensal = float((request.form.get("taxa_juros_mensal") or "0").replace(",", "."))
            except ValueError:
                taxa_juros_mensal = 0
            if taxa_juros_mensal <= 0:
                com_juros = False

    try:
        valor_total = float(valor_str)
        data_lanc = date.fromisoformat(data_str)
    except (ValueError, TypeError):
        flash("Valor ou data inválidos.", "erro")
        return redirect(url_for("lanc.novo", tipo=tipo))

    if tipo not in ("receita", "despesa") or valor_total <= 0:
        flash("Preencha tipo e valor corretamente.", "erro")
        return redirect(url_for("lanc.novo", tipo=tipo))

    if descricao:
        sugestao = db.sugerir_categoria_por_descricao(org_id, descricao)
        if sugestao and not categoria_id:
            categoria_id = sugestao

    arquivo_anexo = request.files.get("anexo")
    tem_anexo = arquivo_anexo and arquivo_anexo.filename
    conteudo_anexo = None
    if tem_anexo:
        conteudo_anexo = arquivo_anexo.read()
        if len(conteudo_anexo) > 8 * 1024 * 1024:
            flash("O arquivo anexado passou de 8 MB - tente uma foto com menos resolução.", "erro")
            return redirect(url_for("lanc.novo", tipo=tipo))

    base = {
        "tipo": tipo, "descricao": descricao, "categoria_id": categoria_id,
        "subcategoria_id": subcategoria_id, "forma_pagamento_id": forma_pagamento_id,
        "cartao_id": cartao_id, "pessoa_id": pessoa_id, "observacao": observacao,
        "conta_bancaria_id": conta_bancaria_id,
    }

    if parcelado and num_parcelas > 1:
        grupo_id = str(uuid.uuid4())
        if com_juros and modo_juros == "valor_parcela":
            valor_parcela = valor_parcela_informado
            diferenca_centavos = 0
            taxa_exibir = None
        elif com_juros:
            valor_parcela = regras_negocio.calcular_parcela_com_juros(valor_total, num_parcelas, taxa_juros_mensal)
            diferenca_centavos = 0
            taxa_exibir = taxa_juros_mensal
        else:
            valor_parcela = round(valor_total / num_parcelas, 2)
            diferenca_centavos = round(valor_total - (valor_parcela * num_parcelas), 2)
            taxa_exibir = None

        for i_parcela in range(num_parcelas):
            valor_desta = valor_parcela + (diferenca_centavos if i_parcela == 0 else 0)
            lanc = db.criar_lancamento(org_id, {
                **base, "data": data_lanc + relativedelta(months=i_parcela), "valor": valor_desta,
                "grupo_parcelamento_id": grupo_id, "parcela_atual": i_parcela + 1, "parcela_total": num_parcelas,
                "taxa_juros_mensal": taxa_exibir,
            }, g.usuario_atual["id"])
            if tem_anexo and i_parcela == 0:
                db.salvar_anexo(lanc["id"], arquivo_anexo.filename, arquivo_anexo.mimetype, conteudo_anexo)

        if com_juros:
            flash(f"Lançamento parcelado em {num_parcelas}x de {_fmt_moeda(valor_parcela)} "
                  f"(total {_fmt_moeda(valor_parcela * num_parcelas)}).", "ok")
        else:
            flash(f"Lançamento parcelado em {num_parcelas}x (1ª parcela {_fmt_moeda(valor_parcela + diferenca_centavos)}, "
                  f"demais {_fmt_moeda(valor_parcela)}) criado.", "ok")
    else:
        lanc = db.criar_lancamento(org_id, {
            **base, "data": data_lanc, "valor": valor_total,
            "grupo_parcelamento_id": None, "parcela_atual": None, "parcela_total": None, "taxa_juros_mensal": None,
        }, g.usuario_atual["id"])
        if tem_anexo:
            db.salvar_anexo(lanc["id"], arquivo_anexo.filename, arquivo_anexo.mimetype, conteudo_anexo)
        flash("Lançamento criado com sucesso.", "ok")

    return redirect(url_for("lanc.novo", tipo=tipo))


@lanc_bp.route("/lancamentos/anexo/<int:anexo_id>")
@login_required
@requer_organizacao
def ver_anexo(anexo_id):
    org_id = g.usuario_atual["organizacao_id"]
    anexo = db.buscar_anexo(anexo_id, org_id)
    if not anexo:
        abort(404)
    return Response(
        bytes(anexo["conteudo"]), mimetype=anexo["mimetype"] or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename=\"{anexo['nome_arquivo']}\""},
    )


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
    total_receitas = sum(float(l["valor"]) for l in lancamentos if l["tipo"] == "receita")
    total_despesas = sum(float(l["valor"]) for l in lancamentos if l["tipo"] == "despesa")
    anexos_por_lancamento = db.anexo_id_por_lancamento([l["id"] for l in lancamentos])
    ctx = _contexto_formulario(org_id)
    return render_template("extrato.html", lancamentos=lancamentos, filtros=filtros,
                            anexos_por_lancamento=anexos_por_lancamento,
                            total_receitas=total_receitas, total_despesas=total_despesas,
                            saldo_filtrado=total_receitas - total_despesas, **ctx)


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
        "observacao": original["observacao"], "taxa_juros_mensal": None,
    }, g.usuario_atual["id"])
    flash("Lançamento duplicado com a data de hoje.", "ok")
    return redirect(url_for("lanc.extrato"))


@lanc_bp.route("/extrato/<int:lid>/editar", methods=["GET", "POST"])
@login_required
@requer_organizacao
def editar(lid):
    org_id = g.usuario_atual["organizacao_id"]
    lancamento = db.buscar_lancamento(lid, org_id)
    if not lancamento:
        flash("Lançamento não encontrado.", "erro")
        return redirect(url_for("lanc.extrato"))

    if request.method == "GET":
        ctx = _contexto_formulario(org_id, tipo=lancamento["tipo"])
        return render_template("lancamento_editar.html", lancamento=lancamento, **ctx)

    valor_str = (request.form.get("valor") or "").replace(".", "").replace(",", ".")
    descricao = request.form.get("descricao", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    forma_pagamento_id = request.form.get("forma_pagamento_id") or None
    data_str = request.form.get("data")

    if not valor_str or not descricao or not categoria_id or not forma_pagamento_id or not data_str:
        flash("Preencha todos os campos obrigatórios.", "erro")
        return redirect(url_for("lanc.editar", lid=lid))

    try:
        valor = float(valor_str)
    except ValueError:
        flash("Valor inválido.", "erro")
        return redirect(url_for("lanc.editar", lid=lid))

    db.atualizar_lancamento(lid, org_id, {
        "data": data_str, "tipo": request.form.get("tipo"), "valor": valor, "descricao": descricao,
        "categoria_id": categoria_id, "subcategoria_id": request.form.get("subcategoria_id") or None,
        "forma_pagamento_id": forma_pagamento_id, "cartao_id": request.form.get("cartao_id") or None,
        "pessoa_id": request.form.get("pessoa_id") or None, "observacao": request.form.get("observacao", "").strip(),
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
        valor_str = (request.form.get("valor") or "").replace(".", "").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            flash("Valor inválido.", "erro")
            return redirect(url_for("lanc.recorrentes"))
        db.criar_template_recorrente(org_id, {
            "nome": request.form.get("nome", "").strip(), "valor": valor,
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
        "grupo_parcelamento_id": None, "parcela_atual": None, "parcela_total": None, "taxa_juros_mensal": None,
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
