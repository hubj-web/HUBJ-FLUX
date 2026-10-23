# -*- coding: utf-8 -*-
"""Holerite (opcional): importar o contracheque como entrada, conferir os números e comparar o que é
descontado em folha com as dívidas cadastradas. Quem preferir pode lançar tudo à mão, como sempre."""
import io
import uuid
from calendar import monthrange
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import folha_analise as fa
from auth import login_required, requer_organizacao, requer_papel
from parsers import sigepe

folha_bp = Blueprint("folha", __name__, url_prefix="/folha")
_pendentes = {}  # token -> holerite lido, guardado só até confirmar (como na importação de fatura)
LIMITE_BYTES = 5_000_000


def _org():
    return g.usuario_atual["organizacao_id"]


def _brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dia_de_recebimento(competencia):
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    return date(ano, mes, min(20, monthrange(ano, mes)[1]))


def _contexto_revisao(org_id, token, h, pessoa_id):
    """Tudo que a tela de revisão mostra: conferências, mudanças, dívidas e avisos."""
    pessoas = db.listar_pessoas(org_id, apenas_disponiveis_lancamento=False)
    if pessoa_id is None:
        sug = fa.sugerir_pessoa(h["servidor_nome"], pessoas)
        pessoa_id = sug["id"] if sug else None
    elif pessoa_id == 0:
        pessoa_id = None
    anterior = db.holerite_anterior(org_id, pessoa_id, h["competencia"], h["fonte"], h["tipo_folha"])
    existente = db.holerite_existente(org_id, pessoa_id, h["competencia"], h["fonte"], h["tipo_folha"], h["autenticacao"])
    parecida = db.entrada_parecida(org_id, h["competencia"], h["liquido"])
    fixos = [dict(f) for f in db.listar_gastos_fixos(org_id)]
    return {"token": token, "h": h, "pessoas": pessoas, "pessoa_id": pessoa_id, "checks": fa.verificar(h),
            "mudancas": fa.comparar(h, anterior) if anterior else None, "anterior": anterior, "existente": existente, "parecida": parecida,
            "dividas": fa.analisar_dividas(h, anterior, fixos), "data_recebimento": _dia_de_recebimento(h["competencia"]).isoformat()}


# ---------- lista ----------

@folha_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = _org()
    ultimos = [h for h in db.ultimos_holerites(org_id) if "NORMAL" in (h["tipo_folha"] or "").upper()]
    return render_template("folha_lista.html", holerites=db.listar_holerites(org_id), renda_sugerida=round(sum(h["liquido"] for h in ultimos), 2) if ultimos else None)


@folha_bp.route("/usar-como-renda", methods=["POST"])
@login_required
@requer_organizacao
def usar_como_renda():
    org_id = _org()
    ultimos = [h for h in db.ultimos_holerites(org_id) if "NORMAL" in (h["tipo_folha"] or "").upper()]
    if not ultimos:
        flash("Ainda não há holerite de folha normal para sugerir a renda.", "erro")
    else:
        renda = round(sum(h["liquido"] for h in ultimos), 2)
        db.salvar_renda_mensal(org_id, renda)
        flash(f"Renda mensal atualizada para {_brl(renda)} (soma do líquido do último holerite de cada pessoa).", "ok")
    return redirect(url_for("folha.index"))


# ---------- importar ----------

@folha_bp.route("/importar", methods=["GET", "POST"])
@login_required
@requer_organizacao
def importar():
    org_id = _org()
    if request.method == "GET":
        return render_template("folha_importar.html")
    arq = request.files.get("pdf")
    if not arq or not arq.filename:
        flash("Escolha o PDF do contracheque.", "erro")
    elif not arq.filename.lower().endswith(".pdf"):
        flash("Envie o contracheque em PDF.", "erro")
    else:
        conteudo = arq.read(LIMITE_BYTES + 1)
        if len(conteudo) > LIMITE_BYTES:
            flash("O arquivo passou de 5 MB.", "erro")
        else:
            try:
                h = sigepe.ler_contracheque(io.BytesIO(conteudo))
            except sigepe.ErroHolerite as e:
                flash(str(e), "erro")
            else:
                token = uuid.uuid4().hex
                if len(_pendentes) >= 20:
                    _pendentes.pop(next(iter(_pendentes)))
                _pendentes[token] = {"org_id": org_id, "h": h}
                return render_template("folha_revisao.html", **_contexto_revisao(org_id, token, h, None))
    return redirect(url_for("folha.importar"))


def _pendente():
    token = request.form.get("token")
    pend = _pendentes.get(token)
    if not pend or pend["org_id"] != _org():
        return None, None
    return token, pend["h"]


def _pessoa_valida(org_id):
    try:
        pid = int(request.form.get("pessoa_id") or 0)
    except ValueError:
        return None
    return pid if pid in {p["id"] for p in db.listar_pessoas(org_id, apenas_disponiveis_lancamento=False)} else None


@folha_bp.route("/importar/revisar", methods=["POST"])
@login_required
@requer_organizacao
def revisar():
    token, h = _pendente()
    if not h:
        flash("A importação expirou. Envie o contracheque de novo.", "erro")
        return redirect(url_for("folha.importar"))
    escolha = request.form.get("pessoa_id")  # None: ainda não escolheu (sugere); "": escolheu 'nenhuma'
    ctx = _contexto_revisao(_org(), token, h, None if escolha is None else (_pessoa_valida(_org()) or 0))
    return render_template("folha_revisao.html", **ctx)


@folha_bp.route("/importar/confirmar", methods=["POST"])
@login_required
@requer_organizacao
def confirmar():
    org_id = _org()
    token, h = _pendente()
    if not h:
        flash("A importação expirou ou já foi concluída. Envie o contracheque de novo se precisar.", "erro")
        return redirect(url_for("folha.importar"))
    pessoa_id = _pessoa_valida(org_id)
    if db.holerite_existente(org_id, pessoa_id, h["competencia"], h["fonte"], h["tipo_folha"], h["autenticacao"]):
        flash("Este holerite já foi importado. Para importar de novo, exclua o anterior na lista.", "erro")
        return redirect(url_for("folha.index"))
    lancar = request.form.get("lancar_entrada") == "on"
    categoria_id = forma_id = None
    if lancar:
        categoria_id, forma_id = db.categoria_e_forma_de_salario(org_id)
        if not categoria_id or not forma_id:
            flash("Para lançar a entrada, cadastre uma categoria de receita e uma forma de pagamento de receita em Configurações.", "erro")
            return redirect(url_for("folha.importar"))
        try:
            data_receb = date.fromisoformat(request.form.get("data_recebimento") or "")
        except ValueError:
            flash("Informe a data em que o salário foi recebido.", "erro")
            return redirect(url_for("folha.importar"))
    hid = db.criar_holerite(org_id, h, pessoa_id, g.usuario_atual["id"])
    if lancar:
        rotulo = f"{h['competencia'][5:7]}/{h['competencia'][:4]}"
        brl = _brl
        lanc = db.criar_lancamento(org_id, {
            "data": data_receb, "tipo": "receita", "valor": h["liquido"], "descricao": f"Salário {rotulo} (holerite)", "categoria_id": categoria_id,
            "subcategoria_id": None, "forma_pagamento_id": forma_id, "cartao_id": None, "pessoa_id": pessoa_id, "grupo_parcelamento_id": None,
            "parcela_atual": None, "parcela_total": None,
            "observacao": f"Líquido do holerite de {rotulo}. Bruto {brl(h['bruto'])}, descontos {brl(h['descontos_total'])}."}, g.usuario_atual["id"])
        db.vincular_lancamento_holerite(hid, lanc["id"])
    del _pendentes[token]
    flash("Holerite importado" + (f" e entrada de {_brl(h['liquido'])} lançada." if lancar else "."), "ok")
    return redirect(url_for("folha.detalhe", holerite_id=hid))


# ---------- um holerite ----------

@folha_bp.route("/<int:holerite_id>")
@login_required
@requer_organizacao
def detalhe(holerite_id):
    org_id = _org()
    h = db.buscar_holerite(org_id, holerite_id)
    if not h:
        flash("Holerite não encontrado.", "erro")
        return redirect(url_for("folha.index"))
    anterior = db.holerite_anterior(org_id, h["pessoa_id"], h["competencia"], h["fonte"], h["tipo_folha"])
    fixos = [dict(f) for f in db.listar_gastos_fixos(org_id)]
    return render_template("folha_detalhe.html", h=h, checks=fa.verificar(h), mudancas=fa.comparar(h, anterior) if anterior else None,
                           dividas=fa.analisar_dividas(h, anterior, fixos))


@folha_bp.route("/<int:holerite_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def excluir(holerite_id):
    if db.excluir_holerite(_org(), holerite_id, request.form.get("tambem_entrada") == "on"):
        flash("Holerite excluído.", "ok")
    else:
        flash("Holerite não encontrado.", "erro")
    return redirect(url_for("folha.index"))


# ---------- folha x dívidas ----------

@folha_bp.route("/dividas")
@login_required
@requer_organizacao
def dividas():
    org_id = _org()
    fixos = [dict(f) for f in db.listar_gastos_fixos(org_id)]
    blocos = []
    for h in db.ultimos_holerites(org_id):
        anterior = db.holerite_anterior(org_id, h["pessoa_id"], h["competencia"], h["fonte"], h["tipo_folha"])
        blocos.append({"h": h, "analise": fa.analisar_dividas(h, anterior, fixos)})
    return render_template("folha_dividas.html", blocos=blocos)


@folha_bp.route("/dividas/marcar", methods=["POST"])
@login_required
@requer_organizacao
def marcar():
    try:
        fixo_id = int(request.form.get("fixo_id"))
    except (TypeError, ValueError):
        flash("Gasto fixo inválido.", "erro")
        return redirect(url_for("folha.dividas"))
    marcar_em_folha = request.form.get("em_folha") == "1"
    db.marcar_fixo_em_folha(_org(), fixo_id, marcar_em_folha)
    flash("Marcado como descontado em folha: deixou de contar como saída do seu bolso." if marcar_em_folha else "Desmarcado: voltou a contar como saída do seu bolso.", "ok")
    return redirect(url_for("folha.dividas"))
