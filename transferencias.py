# -*- coding: utf-8 -*-
"""Família × Empresa: pró-labore, distribuição de lucros, aporte, empréstimo, devolução e reembolso.
Você lança uma vez e o app cria os dois lados: a saída em um espaço e a entrada no outro."""
import re
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import transferencias_db as tdb
import transferencias_logica as tl
from auth import login_required, requer_organizacao, requer_papel
from modulos import requer_modulo, modulo_ativo

transf_bp = Blueprint("transf", __name__, url_prefix="/entre-espacos")
MODULO = "transferencias"
LIMITE_VALOR = 999_999_999.99


def _org():
    return g.usuario_atual["organizacao_id"]


def _numero(texto):
    texto = (texto or "").strip()
    try:
        return float(texto.replace(".", "").replace(",", ".")) if texto else None
    except ValueError:
        return None


def _data(texto):
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _inteiro(texto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return None


def _brl(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _espacos_admin():
    """O cliente do espaço atual e os espaços dele (família, empresas) em que a pessoa é ADMINISTRADORA. Só quem administra os dois lados mexe no dinheiro entre eles."""
    cliente = tdb.cliente_da_organizacao(_org())
    espacos = [e for e in db.listar_espacos_do_usuario(g.usuario_atual["id"]) if cliente and e["cliente_id"] == cliente and e["papel"] == "admin_cliente"]
    return cliente, [e for e in espacos if e["tipo"] == "familia"], [e for e in espacos if e["tipo"] == "empresa"]


def _par(familias, empresas, empresa_escolhida=None):
    """A família e a empresa desta transferência: o espaço em que a pessoa está, mais o outro lado (a empresa escolhida, se houver várias)."""
    atual = _org()
    fam = next((e for e in familias if e["id"] == atual), familias[0] if familias else None)
    emp = next((e for e in empresas if e["id"] == atual), None) or next((e for e in empresas if e["id"] == empresa_escolhida), empresas[0] if empresas else None)
    return fam, emp


@transf_bp.route("/")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def index():
    cliente, familias, empresas = _espacos_admin()
    mes = request.args.get("mes") if re.fullmatch(r"\d{4}-\d{2}", request.args.get("mes") or "") else None
    ids = [e["id"] for e in familias + empresas]
    todas = tdb.listar_transferencias(cliente, ids) if cliente and ids else []
    lista = [t for t in todas if not mes or t["data"].strftime("%Y-%m") == mes]
    atual = _org()
    for t in lista:
        t["direcao"] = "saiu daqui" if t["org_origem_id"] == atual else ("entrou aqui" if t["org_destino_id"] == atual else "")
        t["nome_operacao"] = tl.OPERACOES[t["operacao"]]["nome"] if t["operacao"] in tl.OPERACOES else t["operacao"]
    return render_template("transf_lista.html", transferencias=lista, resumo=tl.resumo(lista), emprestimo_em_aberto=tl.resumo(todas)["emprestimo_em_aberto"],
                           operacoes=tl.OPERACOES, mes=mes, tem_par=bool(familias and empresas), total=round(sum(float(t["valor"]) for t in lista), 2))


@transf_bp.route("/nova", methods=["GET", "POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def nova():
    cliente, familias, empresas = _espacos_admin()
    if not familias or not empresas:
        flash("Para registrar uma transferência, você precisa ser administrador(a) da família e de uma empresa do mesmo cliente.", "erro")
        return redirect(url_for("transf.index"))
    f = request.form
    fam, emp = _par(familias, empresas, _inteiro(f.get("empresa_id")))
    ctx = {"operacoes": tl.OPERACOES, "familia": fam, "empresa": emp, "empresas": empresas, "atual_e_familia": _org() == fam["id"],
           "contas_familia": db.listar_contas_bancarias(fam["id"]), "contas_empresa": db.listar_contas_bancarias(emp["id"]), "hoje": date.today(), "v": {}}
    if request.method == "GET":
        return render_template("transf_form.html", **ctx)
    ctx["v"] = f

    def erro(msg):
        flash(msg, "erro")
        return render_template("transf_form.html", **ctx), 400
    op = tl.operacao(f.get("operacao"))
    valor, data = _numero(f.get("valor")), _data(f.get("data"))
    if op is None:
        return erro("Escolha o tipo de transferência.")
    if valor is None or valor <= 0 or valor > LIMITE_VALOR:
        return erro("Informe um valor maior que zero.")
    if data is None:
        return erro("Informe a data.")
    faltando = [e["nome"] for e in (fam, emp) if not modulo_ativo(e["id"], MODULO)]
    if faltando:
        return erro("O módulo desta função precisa estar ligado nos dois espaços (falta em: " + ", ".join(faltando) + "). Peça a quem administra o sistema.")
    conta_ids = {}
    for chave, org_id in (("conta_familia_id", fam["id"]), ("conta_empresa_id", emp["id"])):
        conta_ids[org_id] = None
        if f.get(chave):
            conta = db.query_one("SELECT id FROM contas_bancarias WHERE id = %s AND organizacao_id = %s AND ativa = true", (_inteiro(f.get(chave)) or 0, org_id))
            if not conta:
                return erro("Conta bancária inválida.")
            conta_ids[org_id] = conta["id"]
    org_origem, org_destino = (emp, fam) if op["de"] == "empresa" else (fam, emp)
    formas = {"origem": tdb.forma_padrao(org_origem["id"], "despesa"), "destino": tdb.forma_padrao(org_destino["id"], "receita")}
    for lado, org in (("origem", org_origem), ("destino", org_destino)):
        if formas[lado] is None:
            return erro(f"Cadastre ao menos uma forma de pagamento em \"{org['nome']}\" (Configurações) antes de registrar a transferência.")
    descricao = (f.get("descricao") or "").strip()[:200] or tl.descricao_padrao(f.get("operacao"), data)
    origem = {"org": org_origem["id"], "nome": org_origem["nome"], "fora": op["fora_origem"], "forma_id": formas["origem"], "conta_id": conta_ids[org_origem["id"]],
              "categoria_id": tdb.categoria_padrao(org_origem["id"], op["cat_origem"], "despesa")}
    destino = {"org": org_destino["id"], "nome": org_destino["nome"], "fora": op["fora_destino"], "forma_id": formas["destino"], "conta_id": conta_ids[org_destino["id"]],
               "categoria_id": tdb.categoria_padrao(org_destino["id"], op["cat_destino"], "receita")}
    tdb.criar_transferencia(cliente, f.get("operacao"), data, valor, descricao, origem, destino, g.usuario_atual["id"])
    flash(f"{op['nome']} de R$ {_brl(valor)} registrado: saiu de \"{org_origem['nome']}\" e entrou em \"{org_destino['nome']}\".", "ok")
    return redirect(url_for("transf.index"))


@transf_bp.route("/<int:transferencia_id>/desfazer", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def desfazer(transferencia_id):
    cliente, familias, empresas = _espacos_admin()
    t = tdb.buscar_transferencia(cliente, transferencia_id) if cliente else None
    meus = {e["id"] for e in familias + empresas}
    if not t or t["org_origem_id"] not in meus or t["org_destino_id"] not in meus:
        flash("Transferência não encontrada.", "erro")
    else:
        tdb.desfazer_transferencia(transferencia_id)
        flash("Transferência desfeita: os dois lançamentos saíram dos extratos.", "ok")
    return redirect(url_for("transf.index"))
