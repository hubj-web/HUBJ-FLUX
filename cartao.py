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


def _mes_da_data_br(data_ddmmyyyy):
    try:
        _, m, y = data_ddmmyyyy.split("/")
        return f"{int(y):04d}-{int(m):02d}"
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
        layout = caixa.detect_layout(tmp_path)
        if layout == "caixa":
            resultado = caixa.parse_invoice(tmp_path)
        elif layout == "caixa_previa":
            resultado = caixa.parse_previa(tmp_path)
        else:
            flash("Não reconheci o layout desta fatura (por enquanto só sei ler faturas Cartões CAIXA e a 'Próxima Fatura' do app).", "erro")
            return redirect(url_for("cartao.importar"))
    except Exception as e:
        flash(f"Falha ao ler o PDF: {e}", "erro")
        return redirect(url_for("cartao.importar"))
    finally:
        os.unlink(tmp_path)

    previa = layout == "caixa_previa"
    final = resultado.get("cartao_final")
    cartoes = db.listar_cartoes_do_banco(org_id, "caixa")
    sugerido = next((c for c in cartoes if c.get("final_cartao") == final), None) or (cartoes[0] if len(cartoes) == 1 else None)

    # O mês da fatura é o mês do VENCIMENTO (quando o dinheiro sai). A prévia não traz vencimento: estimamos pela fatura anterior.
    vencimento = resultado.get("vencimento")
    mes_fatura = _mes_da_data_br(vencimento) if vencimento else None
    venc_iso = _parse_data_br(vencimento) if vencimento else None
    if previa and sugerido:
        ultima = db.ultima_fatura_do_cartao(org_id, sugerido["id"])
        if ultima:
            mes_fatura = cartao_analise.somar_meses(ultima["mes_referencia"], 1)
            dia = ultima["vencimento"].day if ultima.get("vencimento") else 8
            venc_iso = f"{mes_fatura}-{dia:02d}"
    ref_ano = vencimento or resultado.get("data_referencia")

    regras = db.listar_regras_fornecedor(org_id)
    grupos, numeros = {}, set()
    for t in resultado["transacoes"]:
        titular = t["titular"]  # "GERAL" = o que é da fatura e não de uma pessoa: encargos, ajustes, saldo anterior e pagamento
        grupo = grupos.setdefault(titular, {"titular": titular, "rotulo": "Encargos e ajustes da fatura" if titular == "GERAL" else titular,
                                            "transacoes": [], "soma": 0.0})
        if t.get("cartao"):
            numeros.add(t["cartao"])
        t["data_iso"] = _infer_year_and_iso(t["data"], ref_ano)
        regra = cartao_analise.regra_para(regras, t["descricao"])
        t["fornecedor"] = regra["nome"] if regra else None
        t["categoria_sugerida"] = (regra["categoria_nome"] if regra else None) or categorias_cartao.sugerir_categoria(t["descricao"])
        grupo["transacoes"].append(t)
        grupo["soma"] += t["valor"] if t["sinal"] == "D" else -t["valor"]

    soma_total = sum(g_["soma"] for g_ in grupos.values())
    conferencia = {
        "valor_total_fatura": resultado.get("valor_total"), "soma_transacoes": round(soma_total, 2),
        "bate": resultado.get("valor_total") is not None and abs(resultado["valor_total"] - soma_total) < 0.02,
    }
    token = str(uuid.uuid4())
    _pendentes[token] = {
        "organizacao_id": org_id, "arquivo": f.filename, "previa": previa, "banco": "caixa", "final": final,
        "vencimento_iso": venc_iso, "valor_total": resultado.get("valor_total"), "valor_minimo": resultado.get("valor_minimo"),
        "limite_total": resultado.get("limite_total"), "limite_utilizado": resultado.get("limite_utilizado"),
        "limite_disponivel": resultado.get("limite_disponivel"), "grupos": grupos, "numeros": numeros,
    }
    return render_template("cartao_revisao.html", token=token, grupos=grupos, conferencia=conferencia, arquivo=f.filename,
                           previa=previa, final=final, cartoes=cartoes, sugerido_id=sugerido["id"] if sugerido else None,
                           mes_fatura=mes_fatura or "", vencimento_iso=venc_iso or "", data_referencia=resultado.get("data_referencia"))


@cartao_bp.route("/importar/confirmar", methods=["POST"])
@login_required
@requer_organizacao
def confirmar():
    org_id = g.usuario_atual["organizacao_id"]
    pend = _pendentes.get(request.form.get("token"))
    if not pend or pend["organizacao_id"] != org_id:
        flash("A prévia expirou - importe o PDF novamente.", "erro")
        return redirect(url_for("cartao.importar"))
    mes = (request.form.get("mes_fatura") or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        flash("Informe o mês da fatura (o mês do vencimento).", "erro")
        return redirect(url_for("cartao.importar"))

    escolhido = request.form.get("cartao_id")
    cartao_row = db.buscar_cartao(org_id, int(escolhido)) if (escolhido or "").isdigit() else None
    if not cartao_row:
        final = pend["final"]
        cartao_row = db.criar_cartao_conta(org_id, pend["banco"], final, f"Caixa ·{final}" if final else "Cartão Caixa")

    venc_iso = (request.form.get("vencimento") or "").strip() or pend["vencimento_iso"] or None
    fatura_id = db.salvar_fatura(cartao_row["id"], {
        "mes_referencia": mes, "vencimento": venc_iso, "valor_total": pend["valor_total"], "valor_minimo": pend["valor_minimo"],
        "limite_total": pend["limite_total"], "limite_utilizado": pend["limite_utilizado"], "limite_disponivel": pend["limite_disponivel"],
        "arquivo_origem": pend["arquivo"], "numero_cartao_origem": ", ".join(sorted(pend["numeros"])) or None, "previa": pend["previa"],
    }, g.usuario_atual["id"])

    categorias_cache, n = {}, 0
    for titular, grupo in pend["grupos"].items():
        # pessoas vindas de fatura NÃO aparecem no seletor de lançamento (disponivel_lancamento=False)
        pessoa = db.encontrar_ou_criar_pessoa(org_id, titular, disponivel_lancamento=False) if titular != "GERAL" else None
        for t in grupo["transacoes"]:
            nome_cat, categoria_id = t.get("categoria_sugerida"), None
            if nome_cat:
                if nome_cat not in categorias_cache:
                    achada = db.buscar_categoria_por_nome(org_id, nome_cat)
                    categorias_cache[nome_cat] = achada["id"] if achada else (db.garantir_categoria(org_id, nome_cat) if nome_cat == "Encargos financeiros" else None)
                categoria_id = categorias_cache[nome_cat]
            db.inserir_lancamento_cartao(fatura_id, {
                "data_iso": t["data_iso"], "descricao": t["descricao"], "cidade": t.get("cidade"), "valor": t["valor"], "sinal": t["sinal"],
                "parcela_atual": t.get("parcela_atual"), "parcela_total": t.get("parcela_total"), "parcelada": bool(t.get("parcelada")),
                "tipo": t.get("tipo"), "categoria_id": categoria_id, "fornecedor": t.get("fornecedor"), "pessoa_id": pessoa["id"] if pessoa else None,
            })
            n += 1
    del _pendentes[request.form.get("token")]
    rotulo = cartao_analise.rotulo_mes(mes)
    if pend["previa"]:
        flash(f"Prévia de {rotulo} importada ({n} lançamentos). Ela vale até você importar a fatura oficial desse mês, que a substitui.", "ok")
    else:
        flash(f"Fatura de {rotulo} importada: {cartao_row['nome']}, {n} lançamentos.", "ok")
    alertas.registrar_acao(org_id, g.usuario_atual, "fatura de cartão importada",
                           f"{cartao_row['nome']} — {rotulo}" + (" (prévia)" if pend["previa"] else ""), url_for("cartao.painel"))
    return redirect(url_for("cartao.painel", mes=mes))


def _parse_data_br(data_str):
    if not data_str:
        return None
    try:
        d, m, y = data_str.split("/")
        return f"{y}-{m}-{d}"
    except Exception:
        return None


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


@cartao_bp.route("/transacoes")
@login_required
@requer_organizacao
def transacoes():
    org_id = g.usuario_atual["organizacao_id"]
    filtros = {k: (request.args.get(a) or None) for k, a in (
        ("mes_referencia", "mes"), ("cartao_id", "cartao_id"), ("pessoa_id", "pessoa_id"),
        ("busca", "busca"), ("categoria_id", "categoria_id"), ("fornecedor", "fornecedor"), ("lente", "lente"))}
    lancs = db.listar_lancamentos_cartao(org_id, filtros)
    total = sum(float(l["valor"]) for l in lancs if l["sinal"] == "D") - \
        sum(float(l["valor"]) for l in lancs if l["sinal"] == "C")
    return render_template("cartao_transacoes.html", lancamentos=lancs, filtros=filtros, total=total,
                            cartoes=db.listar_cartoes(org_id), pessoas=db.listar_pessoas_todas(org_id),
                            categorias=db.listar_categorias(org_id),
                            meses=[r["mes_referencia"] for r in db.resumo_meses_cartao(org_id, "compra" if filtros.get("lente") == "compra" else "fatura")])



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



@cartao_bp.route("/faturas")
@login_required
@requer_organizacao
def faturas():
    org_id = g.usuario_atual["organizacao_id"]
    meses = cartao_analise.agrupar_faturas_por_mes(db.listar_faturas_organizacao(org_id))
    titulares = {}
    for r in db.titulares_por_fatura(org_id):
        titulares.setdefault(r["fatura_id"], []).append({"nome": r["pessoa_nome"] or "Encargos e ajustes da fatura", "total": float(r["total"]), "n": r["n"]})
    return render_template("cartao_faturas.html", meses=meses, total_geral=sum(m["total"] for m in meses), titulares=titulares)


@cartao_bp.route("/painel")
@login_required
@requer_organizacao
def painel():
    org_id = g.usuario_atual["organizacao_id"]
    lente = "compra" if request.args.get("lente") == "compra" else "fatura"
    resumo = [{**dict(r), "total": float(r["total"] or 0)} for r in db.resumo_meses_cartao(org_id, lente)]
    if not resumo:
        return render_template("cartao_painel.html", resumo=[], lente=lente)

    meses_lista = [r["mes_referencia"] for r in resumo]  # do mais novo para o mais antigo
    mes = request.args.get("mes")
    if mes not in meses_lista:
        mes = meses_lista[0]
    i = meses_lista.index(mes)
    atual = resumo[i]

    categorias_brutas = db.gastos_por_categoria_cartao(org_id, mes, lente)
    compras = sum(float(c["total"]) for c in categorias_brutas)
    maximo = max(r["total"] for r in resumo) or 1
    ultimo_fatura = meses_lista[0] if lente == "fatura" else (db.resumo_meses_cartao(org_id, "fatura") or [{"mes_referencia": meses_lista[0]}])[0]["mes_referencia"]
    proximos = cartao_analise.projetar_parcelas(db.compras_parceladas_cartao(org_id), ultimo_fatura, db.listar_compromissos(org_id))

    return render_template(
        "cartao_painel.html", resumo=resumo, mes=mes, atual=atual, lente=lente,
        mes_anterior=meses_lista[i + 1] if i + 1 < len(meses_lista) else None,
        mes_seguinte=meses_lista[i - 1] if i > 0 else None,
        faturas_mes=db.faturas_do_mes(org_id, mes) if lente == "fatura" else [],
        titulares=[{**dict(t), "total": float(t["total"])} for t in db.titulares_do_mes(org_id, mes, lente)],
        categorias=_com_percentual(categorias_brutas, compras),
        fornecedores=_com_percentual(db.gastos_por_fornecedor_cartao(org_id, mes, 8, lente), compras),
        compras=compras, creditos=db.creditos_cartao_mes(org_id, mes, lente),
        proximos=proximos, total_comprometido=sum(m["total"] for m in proximos),
        total_importado=sum(r["total"] for r in resumo), maximo=maximo,
        barras={r["mes_referencia"]: round(r["total"] / maximo * 100) for r in resumo},
    )
