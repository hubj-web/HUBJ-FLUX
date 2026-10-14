# -*- coding: utf-8 -*-
import os
import re
import tempfile
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

import db
import alertas
import cartao_analise
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

    regras = db.listar_regras_fornecedor(org_id)
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
        regra = cartao_analise.regra_para(regras, t["descricao"])
        t["fornecedor"] = regra["nome"] if regra else None
        t["categoria_sugerida"] = (regra["categoria_nome"] if regra else None) or categorias_cartao.sugerir_categoria(t["descricao"])
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
                "tipo": t.get("tipo"), "categoria_id": categoria_id, "fornecedor": t.get("fornecedor"),
                "pessoa_id": pessoa["id"] if pessoa else None,
            })

    del _pendentes[token]
    flash(f"Fatura importada com sucesso: {len(cartoes_atualizados)} cartão(ões) atualizados.", "ok")
    alertas.registrar_acao(org_id, g.usuario_atual, "fatura de cartão importada",
                           f"Mês {mes_referencia} — {len(cartoes_atualizados)} cartão(ões)", url_for("cartao.painel"))
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
    meses = cartao_analise.agrupar_faturas_por_mes(db.listar_faturas_organizacao(org_id))
    return render_template("cartao_faturas.html", meses=meses, total_geral=sum(m["total"] for m in meses))


@cartao_bp.route("/faturas/<int:fatura_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_fatura(fatura_id):
    db.excluir_fatura(fatura_id, g.usuario_atual["organizacao_id"])
    flash("Fatura excluída.", "ok")
    return redirect(url_for("cartao.faturas"))


@cartao_bp.route("/faturas/mes/<mes>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_mes(mes):
    if not re.fullmatch(r"\d{4}-\d{2}", mes):
        abort(404)
    db.excluir_faturas_mes(g.usuario_atual["organizacao_id"], mes)
    flash("Fatura inteira do mês excluída.", "ok")
    return redirect(url_for("cartao.faturas"))


def _com_percentual(itens, base):
    return [{**dict(i), "total": float(i["total"]), "pct": round(float(i["total"]) / base * 100) if base else 0}
            for i in itens]


@cartao_bp.route("/painel")
@login_required
@requer_organizacao
def painel():
    org_id = g.usuario_atual["organizacao_id"]
    resumo = [{**dict(r), "total": float(r["total"] or 0)} for r in db.resumo_meses_cartao(org_id)]
    if not resumo:
        return render_template("cartao_painel.html", resumo=[])

    meses_lista = [r["mes_referencia"] for r in resumo]  # do mais novo para o mais antigo
    mes = request.args.get("mes")
    if mes not in meses_lista:
        mes = meses_lista[0]
    i = meses_lista.index(mes)
    atual = resumo[i]

    categorias_brutas = db.gastos_por_categoria_cartao(org_id, mes)
    compras = sum(float(c["total"]) for c in categorias_brutas)
    maximo = max(r["total"] for r in resumo) or 1
    proximos = cartao_analise.projetar_parcelas(db.compras_parceladas_cartao(org_id), meses_lista[0], db.listar_compromissos(org_id))

    return render_template(
        "cartao_painel.html", resumo=resumo, mes=mes, atual=atual,
        mes_anterior=meses_lista[i + 1] if i + 1 < len(meses_lista) else None,
        mes_seguinte=meses_lista[i - 1] if i > 0 else None,
        cartoes_mes=db.faturas_do_mes(org_id, mes),
        categorias=_com_percentual(categorias_brutas, compras),
        fornecedores=_com_percentual(db.gastos_por_fornecedor_cartao(org_id, mes, 8), compras),
        compras=compras, creditos=db.creditos_cartao_mes(org_id, mes),
        proximos=proximos, total_comprometido=sum(m["total"] for m in proximos),
        total_importado=sum(r["total"] for r in resumo), maximo=maximo,
        barras={r["mes_referencia"]: round(r["total"] / maximo * 100) for r in resumo},
    )


@cartao_bp.route("/transacoes")
@login_required
@requer_organizacao
def transacoes():
    org_id = g.usuario_atual["organizacao_id"]
    filtros = {k: (request.args.get(a) or None) for k, a in (
        ("mes_referencia", "mes"), ("cartao_id", "cartao_id"), ("pessoa_id", "pessoa_id"),
        ("busca", "busca"), ("categoria_id", "categoria_id"), ("fornecedor", "fornecedor"))}
    lancs = db.listar_lancamentos_cartao(org_id, filtros)
    total = sum(float(l["valor"]) for l in lancs if l["sinal"] == "D") - \
        sum(float(l["valor"]) for l in lancs if l["sinal"] == "C")
    return render_template("cartao_transacoes.html", lancamentos=lancs, filtros=filtros, total=total,
                            cartoes=db.listar_cartoes(org_id), pessoas=db.listar_pessoas_todas(org_id),
                            categorias=db.listar_categorias(org_id),
                            meses=[r["mes_referencia"] for r in db.resumo_meses_cartao(org_id)])



# ---------- Correções manuais ----------

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


@cartao_bp.route("/compra/<int:lc_id>/editar", methods=["GET", "POST"])
@login_required
@requer_organizacao
def editar_compra(lc_id):
    org_id = g.usuario_atual["organizacao_id"]
    l = db.buscar_lancamento_cartao(lc_id, org_id)
    if not l:
        flash("Compra não encontrada.", "erro")
        return redirect(url_for("cartao.transacoes"))
    if request.method == "GET":
        return render_template("cartao_compra_editar.html", l=l, pessoas=db.listar_pessoas_todas(org_id),
                               categorias=db.listar_categorias(org_id, tipo="despesa"))

    valor = _numero(request.form.get("valor"))
    fornecedor = request.form.get("fornecedor", "").strip()
    data_iso = request.form.get("data_iso") or ""
    parcela_atual, parcela_total = _inteiro(request.form.get("parcela_atual")), _inteiro(request.form.get("parcela_total"))
    try:
        datetime.strptime(data_iso, "%Y-%m-%d")
        data_ok = True
    except ValueError:
        data_ok = False
    erro = None
    if valor is None or valor <= 0:
        erro = "Informe um valor válido."
    elif not fornecedor:
        erro = "Informe o fornecedor."
    elif not data_ok:
        erro = "Informe uma data válida."
    elif (parcela_atual is None) != (parcela_total is None):
        erro = "Preencha a parcela atual e o total de parcelas (ou deixe as duas em branco)."
    elif parcela_atual is not None and not (1 <= parcela_atual <= parcela_total <= 60):
        erro = "Parcela inválida: a atual deve ficar entre 1 e o total (máximo 60)."
    if erro:
        flash(erro, "erro")
        return redirect(url_for("cartao.editar_compra", lc_id=lc_id))

    categoria_id = request.form.get("categoria_id") or None
    db.atualizar_lancamento_cartao(lc_id, org_id, {
        "fornecedor": fornecedor, "data_iso": data_iso, "valor": valor, "categoria_id": categoria_id,
        "pessoa_id": request.form.get("pessoa_id") or None, "parcela_atual": parcela_atual,
        "parcela_total": parcela_total, "nao_projetar": request.form.get("nao_projetar") == "on",
    })
    mensagem = "Compra atualizada."
    padrao = (l["descricao"] or "").strip().upper()
    if request.form.get("criar_regra") == "on" and padrao:
        db.criar_regra_fornecedor(org_id, padrao, fornecedor, categoria_id)
        n = db.aplicar_regra_fornecedor(org_id, padrao, fornecedor, categoria_id)
        mensagem = f"Compra atualizada. Regra criada e aplicada em {n} compra(s) que contêm \"{padrao}\"."
    flash(mensagem, "ok")
    return redirect(url_for("cartao.transacoes", mes=l["mes_referencia"]))


@cartao_bp.route("/compra/<int:lc_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_compra(lc_id):
    org_id = g.usuario_atual["organizacao_id"]
    l = db.buscar_lancamento_cartao(lc_id, org_id)
    if l and db.excluir_lancamento_cartao(lc_id, org_id):
        flash("Compra excluída e total da fatura acertado.", "ok")
        return redirect(url_for("cartao.transacoes", mes=l["mes_referencia"]))
    flash("Compra não encontrada.", "erro")
    return redirect(url_for("cartao.transacoes"))


@cartao_bp.route("/compromissos", methods=["GET", "POST"])
@login_required
@requer_organizacao
def compromissos():
    org_id = g.usuario_atual["organizacao_id"]
    resumo = db.resumo_meses_cartao(org_id)
    ultimo = resumo[0]["mes_referencia"] if resumo else None
    if request.method == "POST":
        descricao = request.form.get("descricao", "").strip()
        valor, n = _numero(request.form.get("valor_parcela")), _inteiro(request.form.get("num_parcelas"))
        mes = request.form.get("mes_inicial") or ""
        erro = None
        if not descricao or valor is None or valor <= 0 or n is None or not (1 <= n <= 60):
            erro = "Preencha a descrição, o valor da parcela e o número de parcelas (1 a 60)."
        elif not re.fullmatch(r"\d{4}-\d{2}", mes):
            erro = "Escolha o mês da 1ª parcela."
        elif ultimo and mes <= ultimo:
            erro = (f"A 1ª parcela precisa ser depois da última fatura importada ({cartao_analise.rotulo_mes(ultimo)}). "
                    "Compras de meses já importados se corrigem na própria fatura.")
        if erro:
            flash(erro, "erro")
        else:
            db.criar_compromisso(org_id, descricao, valor, n, mes, request.form.get("pessoa_id") or None)
            flash("Compra parcelada cadastrada: ela já entra na projeção dos próximos meses.", "ok")
        return redirect(url_for("cartao.compromissos"))
    lista = [{**dict(k), "ativo": (not ultimo) or k["mes_inicial"] > ultimo} for k in db.listar_compromissos(org_id)]
    return render_template("cartao_compromissos.html", compromissos=lista, ultimo=ultimo,
                           mes_minimo=cartao_analise.somar_meses(ultimo, 1) if ultimo else None,
                           pessoas=db.listar_pessoas_todas(org_id))


@cartao_bp.route("/compromissos/<int:compromisso_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_compromisso(compromisso_id):
    db.excluir_compromisso(compromisso_id, g.usuario_atual["organizacao_id"])
    flash("Compra parcelada removida da projeção.", "ok")
    return redirect(url_for("cartao.compromissos"))
