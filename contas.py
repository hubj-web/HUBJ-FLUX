# -*- coding: utf-8 -*-
"""Módulo Contas a pagar e a receber (espaço Empresa): contas com vencimento e situação, clientes e fornecedores,
e a baixa, que lança o pagamento ou o recebimento no extrato."""
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import contas_db as cdb
import contas_logica as cl
import db
from auth import login_required, requer_organizacao, requer_papel
from modulos import requer_modulo

contas_bp = Blueprint("contas", __name__, url_prefix="/contas")
LIMITE_VALOR = 999_999_999.99
MODULO = "contas_pagar_receber"
TIPOS_PARCEIRO = ("cliente", "fornecedor", "ambos")


def _org():
    return g.usuario_atual["organizacao_id"]


def _numero(texto):
    texto = (texto or "").strip()
    try:
        return float(texto.replace(".", "").replace(",", ".")) if texto else None
    except ValueError:
        return None


def _inteiro(texto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return None


def _data(texto):
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _brl(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dmy(d):
    return d.strftime("%d/%m/%Y")


def _tipo(valor):
    return valor if valor in ("pagar", "receber") else "pagar"


def _tipo_lancamento(tipo_titulo):
    return "despesa" if tipo_titulo == "pagar" else "receita"


def _contexto_form(tipo, titulo=None, valores=None):
    org = _org()
    return {"tipo": tipo, "titulo": titulo, "v": valores or {},
            "categorias": db.listar_categorias(org, tipo=_tipo_lancamento(tipo)),
            "parceiros": cdb.listar_parceiros(org, "fornecedor" if tipo == "pagar" else "cliente")}


# ---------- lista ----------

@contas_bp.route("/")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def index():
    org, hoje = _org(), date.today()
    tipo = _tipo(request.args.get("tipo"))
    situacao = request.args.get("situacao") if request.args.get("situacao") in cl.SITUACOES_LISTA else "abertos"
    de, ate = _data(request.args.get("de")), _data(request.args.get("ate"))
    q = (request.args.get("q") or "").strip()[:80]
    parceiro_id = _inteiro(request.args.get("parceiro"))
    titulos = cdb.listar_titulos(org, tipo, situacao, hoje, de, ate, q or None, parceiro_id)
    for t in titulos:
        t["situacao"] = cl.situacao(t["status"], t["vencimento"], hoje)
        t["dias"] = cl.dias_para_vencer(t["vencimento"], hoje)
    return render_template("contas_lista.html", tipo=tipo, situacao=situacao, titulos=titulos, resumo=cdb.resumo_titulos(org, hoje), hoje=hoje,
                           total_lista=round(sum(float(t["valor"]) for t in titulos), 2), rotulo=cl.ROTULO_SITUACAO, de=de, ate=ate, q=q, parceiro_id=parceiro_id,
                           parceiros=cdb.listar_parceiros(org, "fornecedor" if tipo == "pagar" else "cliente", apenas_ativos=False))


# ---------- cadastrar e editar ----------

def _ler_titulo(f, tipo, criando):
    """Confere o formulário. Devolve (dados, erro). O cliente ou fornecedor novo só é criado depois que todo o resto está certo."""
    org = _org()
    descricao = (f.get("descricao") or "").strip()[:200]
    valor, vencimento = _numero(f.get("valor")), _data(f.get("vencimento"))
    if not descricao:
        return None, "Informe a descrição da conta."
    if valor is None or valor <= 0 or valor > LIMITE_VALOR:
        return None, "Informe um valor maior que zero."
    if vencimento is None:
        return None, "Informe a data de vencimento."
    categoria_id = None
    if f.get("categoria_id"):
        cat = db.query_one("SELECT id, tipo FROM categorias WHERE id = %s AND organizacao_id = %s AND ativa = true", (_inteiro(f.get("categoria_id")) or 0, org))
        if not cat or cat["tipo"] != _tipo_lancamento(tipo):
            return None, "Escolha uma categoria de " + ("despesa" if tipo == "pagar" else "receita") + " para esta conta."
        categoria_id = cat["id"]
    parcelas = 1
    if criando:
        parcelas = _inteiro(f.get("parcelas"))
        parcelas = 1 if parcelas is None else parcelas  # campo vazio ou ilegível = 1 só; 0 e números fora do limite são recusados
        if not 1 <= parcelas <= 60:
            return None, "O número de parcelas deve estar entre 1 e 60."
    parceiro_id = None
    necessario = "fornecedor" if tipo == "pagar" else "cliente"
    novo_nome = (f.get("parceiro_novo") or "").strip()[:150]
    if novo_nome:
        p = cdb.parceiro_por_nome(org, novo_nome) or cdb.criar_parceiro(org, novo_nome, necessario)
        parceiro_id = p["id"]
    elif f.get("parceiro_id"):
        p = cdb.buscar_parceiro(org, _inteiro(f.get("parceiro_id")) or 0)
        if not p or not p["ativo"]:
            return None, "Cliente ou fornecedor inválido."
        parceiro_id = p["id"]
    if parceiro_id:
        cdb.ampliar_tipo_parceiro(org, parceiro_id, necessario)
    return {"descricao": descricao, "valor": valor, "vencimento": vencimento, "categoria_id": categoria_id, "parceiro_id": parceiro_id,
            "numero_documento": (f.get("numero_documento") or "").strip()[:40] or None, "observacao": (f.get("observacao") or "").strip()[:300] or None,
            "parcelas": parcelas}, None


@contas_bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def novo():
    tipo = _tipo(request.values.get("tipo"))
    if request.method == "GET":
        return render_template("contas_form.html", **_contexto_form(tipo, valores={"vencimento": date.today().isoformat()}))
    dados, erro = _ler_titulo(request.form, tipo, criando=True)
    if erro:
        flash(erro, "erro")
        return render_template("contas_form.html", **_contexto_form(tipo, valores=request.form)), 400
    n = dados.pop("parcelas")
    lista = [{**dados, "tipo": tipo, "descricao": cl.descricao_da_parcela(dados["descricao"], num, n), "vencimento": venc,
              "parcela_atual": num if n > 1 else None, "parcela_total": n if n > 1 else None} for num, venc in cl.gerar_parcelas(dados["vencimento"], n)]
    cdb.criar_titulos(_org(), lista, g.usuario_atual["id"])
    if n == 1:
        flash("Conta a pagar cadastrada." if tipo == "pagar" else "Conta a receber cadastrada.", "ok")
    else:
        flash(f"{n} parcelas cadastradas, de {_dmy(lista[0]['vencimento'])} a {_dmy(lista[-1]['vencimento'])}.", "ok")
    return redirect(url_for("contas.index", tipo=tipo))


def _titulo_ou_none(titulo_id):
    t = cdb.buscar_titulo(_org(), titulo_id)
    if not t:
        flash("Conta não encontrada.", "erro")
    return t


@contas_bp.route("/<int:titulo_id>/editar", methods=["GET", "POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def editar(titulo_id):
    t = _titulo_ou_none(titulo_id)
    if not t:
        return redirect(url_for("contas.index"))
    if t["status"] != "aberto":
        flash("Só dá para editar contas em aberto. Se ela já foi paga, desfaça a baixa antes.", "erro")
        return redirect(url_for("contas.index", tipo=t["tipo"]))
    if request.method == "GET":
        return render_template("contas_form.html", **_contexto_form(t["tipo"], titulo=t, valores={**t, "vencimento": t["vencimento"].isoformat(), "valor": _brl(t["valor"])}))
    dados, erro = _ler_titulo(request.form, t["tipo"], criando=False)
    if erro:
        flash(erro, "erro")
        return render_template("contas_form.html", **_contexto_form(t["tipo"], titulo=t, valores=request.form)), 400
    dados.pop("parcelas")
    cdb.atualizar_titulo(_org(), titulo_id, dados)
    flash("Conta atualizada.", "ok")
    return redirect(url_for("contas.index", tipo=t["tipo"]))


# ---------- baixa (pagar ou receber) ----------

@contas_bp.route("/<int:titulo_id>/baixar", methods=["GET", "POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def baixar(titulo_id):
    org = _org()
    t = _titulo_ou_none(titulo_id)
    if not t:
        return redirect(url_for("contas.index"))
    if t["status"] != "aberto":
        flash("Esta conta já foi " + ("baixada." if t["status"] == "pago" else "cancelada."), "erro")
        return redirect(url_for("contas.index", tipo=t["tipo"]))
    lanc_tipo = _tipo_lancamento(t["tipo"])
    ctx = {"t": t, "formas": db.listar_formas_pagamento(org, lanc_tipo), "contas_bancarias": db.listar_contas_bancarias(org), "hoje": date.today(), "v": {}}
    if request.method == "GET":
        return render_template("contas_baixar.html", **ctx)
    f = request.form
    data_pag, valor_pago = _data(f.get("data_pagamento")), _numero(f.get("valor_pago"))
    forma = db.query_one("SELECT id FROM formas_pagamento WHERE id = %s AND organizacao_id = %s AND ativa = true AND aplica_a IN (%s, 'ambos')", (_inteiro(f.get("forma_pagamento_id")) or 0, org, lanc_tipo))
    conta_id = None
    if f.get("conta_bancaria_id"):
        conta = db.query_one("SELECT id FROM contas_bancarias WHERE id = %s AND organizacao_id = %s AND ativa = true", (_inteiro(f.get("conta_bancaria_id")) or 0, org))
        conta_id = conta["id"] if conta else -1
    erro = ("Informe a data em que foi " + ("paga." if t["tipo"] == "pagar" else "recebida.") if data_pag is None else
            "Informe um valor maior que zero." if valor_pago is None or valor_pago <= 0 or valor_pago > LIMITE_VALOR else
            "Escolha a forma de pagamento." if forma is None else "Conta bancária inválida." if conta_id == -1 else None)
    if erro:
        flash(erro, "erro")
        return render_template("contas_baixar.html", **{**ctx, "v": f}), 400
    obs = f"{'Pago' if t['tipo'] == 'pagar' else 'Recebido'} referente à conta com vencimento em {_dmy(t['vencimento'])}"
    obs += f" · {t['parceiro_nome']}" if t["parceiro_nome"] else ""
    obs += f" · documento {t['numero_documento']}" if t["numero_documento"] else ""
    lanc = db.criar_lancamento(org, {"data": data_pag, "tipo": lanc_tipo, "valor": valor_pago, "descricao": t["descricao"], "categoria_id": t["categoria_id"],
                                     "subcategoria_id": None, "forma_pagamento_id": forma["id"], "cartao_id": None, "pessoa_id": None, "grupo_parcelamento_id": None,
                                     "parcela_atual": t["parcela_atual"], "parcela_total": t["parcela_total"], "observacao": obs[:300], "conta_bancaria_id": conta_id},
                               g.usuario_atual["id"])
    if not cdb.marcar_pago(org, titulo_id, data_pag, valor_pago, forma["id"], lanc["id"]):
        db.excluir_lancamento(lanc["id"], org)  # outra pessoa baixou no mesmo instante: não deixa lançamento em dobro
        flash("Esta conta acabou de ser baixada por outra pessoa. Nada foi lançado em dobro.", "erro")
    else:
        flash(("Pagamento" if t["tipo"] == "pagar" else "Recebimento") + f" de R$ {_brl(valor_pago)} lançado no extrato.", "ok")
    return redirect(url_for("contas.index", tipo=t["tipo"]))


@contas_bp.route("/<int:titulo_id>/desfazer", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def desfazer(titulo_id):
    t = _titulo_ou_none(titulo_id)
    if not t:
        return redirect(url_for("contas.index"))
    if t["status"] != "pago":
        flash("Só dá para desfazer a baixa de uma conta que está paga.", "erro")
        return redirect(url_for("contas.index", tipo=t["tipo"]))
    if t["lancamento_id"]:
        db.excluir_lancamento(t["lancamento_id"], _org())
    cdb.reabrir_titulo(_org(), titulo_id)
    flash('Baixa desfeita: a conta voltou para "em aberto" e o lançamento saiu do extrato.', "ok")
    return redirect(url_for("contas.index", tipo=t["tipo"]))


@contas_bp.route("/<int:titulo_id>/cancelar", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def cancelar(titulo_id):
    t = _titulo_ou_none(titulo_id)
    if not t:
        return redirect(url_for("contas.index"))
    if t["status"] != "aberto":
        flash("Só dá para cancelar uma conta em aberto.", "erro")
    else:
        cdb.cancelar_titulo(_org(), titulo_id)
        flash("Conta cancelada.", "ok")
    return redirect(url_for("contas.index", tipo=t["tipo"]))


@contas_bp.route("/<int:titulo_id>/reabrir", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def reabrir(titulo_id):
    t = _titulo_ou_none(titulo_id)
    if not t:
        return redirect(url_for("contas.index"))
    if t["status"] != "cancelado":
        flash("Só dá para reabrir uma conta cancelada.", "erro")
    else:
        cdb.reabrir_titulo(_org(), titulo_id)
        flash("Conta reaberta.", "ok")
    return redirect(url_for("contas.index", tipo=t["tipo"]))


@contas_bp.route("/<int:titulo_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def excluir(titulo_id):
    t = _titulo_ou_none(titulo_id)
    if not t:
        return redirect(url_for("contas.index"))
    if t["status"] == "pago":
        flash("Uma conta paga não pode ser excluída. Desfaça a baixa antes.", "erro")
    else:
        cdb.excluir_titulo(_org(), titulo_id)
        flash("Conta excluída.", "ok")
    return redirect(url_for("contas.index", tipo=t["tipo"]))


# ---------- clientes e fornecedores ----------

def _ler_parceiro(f):
    nome = (f.get("nome") or "").strip()[:150]
    tipo = f.get("tipo") if f.get("tipo") in TIPOS_PARCEIRO else "ambos"
    if not nome:
        return None, "Informe o nome."
    return {"nome": nome, "tipo": tipo, "documento": (f.get("documento") or "").strip()[:20] or None, "email": (f.get("email") or "").strip()[:150] or None,
            "telefone": (f.get("telefone") or "").strip()[:30] or None, "observacao": (f.get("observacao") or "").strip()[:300] or None}, None


@contas_bp.route("/parceiros", methods=["GET", "POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def parceiros():
    org = _org()
    if request.method == "POST":
        d, erro = _ler_parceiro(request.form)
        if erro:
            flash(erro, "erro")
        elif cdb.parceiro_por_nome(org, d["nome"]):
            flash(f'Já existe um cliente ou fornecedor com o nome "{d["nome"]}".', "erro")
        else:
            cdb.criar_parceiro(org, **d)
            flash(f'"{d["nome"]}" cadastrado.', "ok")
        return redirect(url_for("contas.parceiros"))
    return render_template("contas_parceiros.html", parceiros=cdb.listar_parceiros(org, apenas_ativos=False))


@contas_bp.route("/parceiros/<int:parceiro_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def salvar_parceiro(parceiro_id):
    org = _org()
    if not cdb.buscar_parceiro(org, parceiro_id):
        flash("Cadastro não encontrado.", "erro")
        return redirect(url_for("contas.parceiros"))
    d, erro = _ler_parceiro(request.form)
    outro = cdb.parceiro_por_nome(org, d["nome"]) if d else None
    if erro:
        flash(erro, "erro")
    elif outro and outro["id"] != parceiro_id:
        flash(f'Já existe um cliente ou fornecedor com o nome "{d["nome"]}".', "erro")
    else:
        cdb.atualizar_parceiro(org, parceiro_id, **d)
        flash("Cadastro atualizado.", "ok")
    return redirect(url_for("contas.parceiros"))


@contas_bp.route("/parceiros/<int:parceiro_id>/ativo", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
def ativar_parceiro(parceiro_id):
    org = _org()
    p = cdb.buscar_parceiro(org, parceiro_id)
    if not p:
        flash("Cadastro não encontrado.", "erro")
    else:
        cdb.definir_parceiro_ativo(org, parceiro_id, not p["ativo"])
        flash(f'"{p["nome"]}" ' + ("desativado: não aparece mais nas listas para escolher." if p["ativo"] else "reativado."), "ok")
    return redirect(url_for("contas.parceiros"))
