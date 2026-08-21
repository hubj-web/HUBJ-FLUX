# -*- coding: utf-8 -*-
import os
import tempfile
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
from auth import login_required, requer_organizacao
from parsers import caixa
import categorias_cartao

cartao_bp = Blueprint("cartao", __name__, url_prefix="/cartao")

_pendentes = {}


def _infer_year_and_iso(data_ddmm, vencimento_ddmmyyyy):
    try:
        d, m = data_ddmm.split("/")
        d, m = int(d), int(m)
    except Exception:
        return None
    try:
        venc_m, venc_y = vencimento_ddmmyyyy.split("/")[1:3]
        venc_m, venc_y = int(venc_m), int(venc_y)
    except Exception:
        venc_y, venc_m = datetime.now().year, datetime.now().month
    year = venc_y - 1 if m > venc_m else venc_y
    try:
        return f"{year:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


def _default_mes_referencia(vencimento_ddmmyyyy):
    try:
        _, m, y = vencimento_ddmmyyyy.split("/")
        m, y = int(m), int(y)
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        return f"{y:04d}-{m:02d}"
    except Exception:
        return None


@cartao_bp.route("/importar", methods=["GET", "POST"])
@login_required
@requer_organizacao
def importar():
    if request.method == "GET":
        return render_template("cartao_importar.html")

    org_id = g.usuario_atual["organizacao_id"]
    if "pdf" not in request.files or not request.files["pdf"].filename:
        flash("Selecione um arquivo PDF.", "erro")
        return redirect(url_for("cartao.importar"))

    f = request.files["pdf"]
    if not f.filename.lower().endswith(".pdf"):
        flash("Envie um arquivo PDF.", "erro")
        return redirect(url_for("cartao.importar"))

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        banco = caixa.detect_bank(tmp_path)
        if banco != "caixa":
            flash("Não reconheci o layout desta fatura (por enquanto só sei ler faturas Cartões CAIXA).", "erro")
            return redirect(url_for("cartao.importar"))
        resultado = caixa.parse_invoice(tmp_path)
    except Exception as e:
        flash(f"Falha ao ler o PDF: {e}", "erro")
        return redirect(url_for("cartao.importar"))
    finally:
        os.unlink(tmp_path)

    vencimento = resultado.get("vencimento")
    cartao_principal = resultado.get("cartao_final")

    # Nome do titular principal: preferimos a forma como aparece nas
    # seções de cartão (abreviada) - assim fica consistente com as demais
    # seções da MESMA fatura, evitando cadastrar a mesma pessoa duas vezes.
    titular_principal = None
    for t in resultado["transacoes"]:
        if t["titular"] != "GERAL" and t["cartao"] == cartao_principal:
            titular_principal = t["titular"]
            break
    if not titular_principal:
        titular_principal = resultado.get("titular") or "GERAL"

    grupos = {}
    for t in resultado["transacoes"]:
        titular = t["titular"]
        cartao_num = t["cartao"]
        if titular == "GERAL":
            titular, cartao_num = titular_principal, (cartao_num or cartao_principal)
        chave = titular  # agrupa por PESSOA, não mais por (pessoa, número do cartão)
        grupo = grupos.setdefault(chave, {"titular": titular, "cartoes_numeros": set(), "transacoes": [], "soma": 0.0})
        if cartao_num:
            grupo["cartoes_numeros"].add(cartao_num)
        t["data_iso"] = _infer_year_and_iso(t["data"], vencimento)
        t["categoria_sugerida"] = categorias_cartao.sugerir_categoria(t["descricao"])
        grupo["transacoes"].append(t)
        grupo["soma"] += t["valor"] if t["sinal"] == "D" else -t["valor"]

    soma_total = sum(g["soma"] for g in grupos.values())
    conferencia = {
        "valor_total_fatura": resultado.get("valor_total"),
        "soma_transacoes": round(soma_total, 2),
        "bate": resultado.get("valor_total") is not None and abs(resultado["valor_total"] - soma_total) < 0.02,
    }

    token = str(uuid.uuid4())
    _pendentes[token] = {
        "organizacao_id": org_id, "arquivo": f.filename, "vencimento": vencimento,
        "mes_referencia": _default_mes_referencia(vencimento),
        "valor_total": resultado.get("valor_total"), "valor_minimo": resultado.get("valor_minimo"),
        "limite_total": resultado.get("limite_total"), "limite_utilizado": resultado.get("limite_utilizado"),
        "limite_disponivel": resultado.get("limite_disponivel"), "grupos": grupos,
    }

    return render_template("cartao_revisao.html", token=token, grupos=grupos, conferencia=conferencia,
                            vencimento=vencimento, arquivo=f.filename,
                            mes_referencia=_pendentes[token]["mes_referencia"],
                            categorias=db.listar_categorias(org_id))


@cartao_bp.route("/importar/confirmar", methods=["POST"])
@login_required
@requer_organizacao
def confirmar():
    org_id = g.usuario_atual["organizacao_id"]
    token = request.form.get("token")
    pend = _pendentes.get(token)
    if not pend or pend["organizacao_id"] != org_id:
        flash("A prévia expirou - importe o PDF novamente.", "erro")
        return redirect(url_for("cartao.importar"))

    mes_referencia = request.form.get("mes_referencia") or pend["mes_referencia"]
    cartoes_atualizados = []

    for titular, grupo in pend["grupos"].items():
        # pessoas vindas de fatura NÃO aparecem no seletor de lançamento
        # (disponivel_lancamento=False) - só as cadastradas manualmente.
        pessoa = db.encontrar_ou_criar_pessoa(org_id, titular, disponivel_lancamento=False) if titular != "GERAL" else None
        cartao_row = db.encontrar_ou_criar_cartao_por_pessoa(org_id, pessoa["id"], titular) if pessoa else \
            db.encontrar_ou_criar_cartao_por_pessoa(org_id, None, "Fatura Geral")
        cartoes_atualizados.append(cartao_row["nome"])

        numeros = ", ".join(sorted(grupo["cartoes_numeros"])) if grupo["cartoes_numeros"] else None
        fatura_id = db.salvar_fatura(cartao_row["id"], {
            "mes_referencia": mes_referencia, "vencimento": _parse_data_br(pend["vencimento"]),
            "valor_total": pend["valor_total"] if len(pend["grupos"]) == 1 else round(grupo["soma"], 2),
            "valor_minimo": pend["valor_minimo"], "limite_total": pend["limite_total"],
            "limite_utilizado": pend["limite_utilizado"], "limite_disponivel": pend["limite_disponivel"],
            "arquivo_origem": pend["arquivo"], "numero_cartao_origem": numeros,
        }, g.usuario_atual["id"])

        for t in grupo["transacoes"]:
            categoria_id = None
            if t.get("categoria_sugerida"):
                cat = db.buscar_categoria_por_nome(org_id, t["categoria_sugerida"])
                categoria_id = cat["id"] if cat else None
            db.inserir_lancamento_cartao(fatura_id, {
                "data_iso": t["data_iso"], "descricao": t["descricao"], "cidade": t.get("cidade"),
                "valor": t["valor"], "sinal": t["sinal"], "parcela_atual": t.get("parcela_atual"),
                "parcela_total": t.get("parcela_total"), "parcelada": bool(t.get("parcelada")),
                "tipo": t.get("tipo"), "categoria_id": categoria_id,
                "pessoa_id": pessoa["id"] if pessoa else None,
            })

    del _pendentes[token]
    flash(f"Fatura importada com sucesso: {len(cartoes_atualizados)} cartão(ões) atualizados.", "ok")
    return redirect(url_for("cartao.painel"))


def _parse_data_br(data_str):
    if not data_str:
        return None
    try:
        d, m, y = data_str.split("/")
        return f"{y}-{m}-{d}"
    except Exception:
        return None


@cartao_bp.route("/faturas")
@login_required
@requer_organizacao
def faturas():
    org_id = g.usuario_atual["organizacao_id"]
    return render_template("cartao_faturas.html", faturas=db.listar_faturas_organizacao(org_id))


@cartao_bp.route("/faturas/<int:fatura_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_fatura(fatura_id):
    db.excluir_fatura(fatura_id, g.usuario_atual["organizacao_id"])
    flash("Fatura excluída.", "ok")
    return redirect(url_for("cartao.faturas"))


@cartao_bp.route("/painel")
@login_required
@requer_organizacao
def painel():
    org_id = g.usuario_atual["organizacao_id"]
    faturas = db.ultimas_faturas_por_cartao(org_id)
    total_faturas = sum(float(f["valor_total"] or 0) for f in faturas)
    total_disponivel = sum(float(f["limite_disponivel"] or 0) for f in faturas)
    return render_template("cartao_painel.html", faturas=faturas,
                            total_faturas=total_faturas, total_disponivel=total_disponivel)


@cartao_bp.route("/transacoes")
@login_required
@requer_organizacao
def transacoes():
    org_id = g.usuario_atual["organizacao_id"]
    filtros = {
        "mes_referencia": request.args.get("mes") or None,
        "cartao_id": request.args.get("cartao_id") or None,
        "pessoa_id": request.args.get("pessoa_id") or None,
        "busca": request.args.get("busca") or None,
    }
    lancs = db.listar_lancamentos_cartao(org_id, filtros)
    total = sum(float(l["valor"]) for l in lancs if l["sinal"] == "D") - \
        sum(float(l["valor"]) for l in lancs if l["sinal"] == "C")
    return render_template("cartao_transacoes.html", lancamentos=lancs, filtros=filtros, total=total,
                            cartoes=db.listar_cartoes(org_id), pessoas=db.listar_pessoas_todas(org_id))
