# -*- coding: utf-8 -*-
"""Módulo Resultado e fluxo de caixa (espaço Empresa): resultado do mês, caixa previsto e calendário de obrigações. Só o administrador vê."""
import re
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import cartao_analise
import db
import financeiro_db as fdb
import financeiro_logica as fl
import planejamento_mensal as pm
from auth import login_required, requer_organizacao, requer_papel
from mensal import _carregar as carregar_planejamento
from modulos import requer_modulo

fin_bp = Blueprint("fin", __name__, url_prefix="/financeiro")
MODULO = "resultado_caixa"


def _org():
    return g.usuario_atual["organizacao_id"]


def _numero(texto):
    texto = (texto or "").strip()
    try:
        return float(texto.replace(".", "").replace(",", ".")) if texto else None
    except ValueError:
        return None


def construir_fluxo(org_id, n, saldo_param=None):
    """O caixa previsto dos próximos n meses. Sem saldo informado, parte do saldo das contas bancárias."""
    d = carregar_planejamento(org_id, n)
    desloc = pm.calcular_deslocamento(d["resumo"])
    venc_fatura = {}
    for f in d["resumo"]:
        chave = f["vencimento"].strftime("%Y-%m") if f.get("vencimento") else cartao_analise.somar_meses(f["mes_referencia"], desloc)
        venc_fatura.setdefault(chave, f.get("vencimento"))
    saldo_contas, n_contas = fdb.saldo_das_contas(org_id)
    saldo = saldo_param if saldo_param is not None else saldo_contas
    fluxo = fl.montar_fluxo(d["hoje"], n, saldo, fdb.titulos_abertos(org_id), d["meses"], venc_fatura)
    return fluxo, {"saldo_contas": saldo_contas, "n_contas": n_contas, "informado": saldo_param is not None}


def alerta_caixa(org_id):
    """O primeiro mês em que o caixa previsto fica negativo (ou None). Usado no aviso do Mês."""
    fluxo, _ = construir_fluxo(org_id, 6)
    return fluxo["primeiro_negativo"]


def _ctx_base(aba):
    return {"aba": aba, "rotulo": cartao_analise.rotulo_mes}


@fin_bp.route("/")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def index():
    return redirect(url_for("fin.resultado"))


@fin_bp.route("/resultado")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def resultado():
    org = _org()
    mes = request.args.get("mes") if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", request.args.get("mes") or "") else date.today().strftime("%Y-%m")
    ant = cartao_analise.somar_meses(mes, -1)
    t, t_ant = db.totais_mes(org, mes), db.totais_mes(org, ant)
    nomes = fdb.nomes_categorias(org)
    desp = db.realizado_por_categoria_mes(org, mes, incluir_sem_categoria=True)
    ajuste = round(t["despesas"] - sum(desp.values()), 2)
    if ajuste > 0.01:
        desp = {**desp, "__outros": ajuste}
        nomes = {**nomes, "__outros": "Outros (não classificados)"}
    rec = fdb.receitas_por_categoria_mes(org, mes)
    res, res_ant = round(t["receitas"] - t["despesas"], 2), round(t_ant["receitas"] - t_ant["despesas"], 2)
    serie = []
    for i in range(5, -1, -1):
        m = cartao_analise.somar_meses(mes, -i)
        x = t if m == mes else db.totais_mes(org, m)
        serie.append({"mes": m, "receitas": x["receitas"], "despesas": x["despesas"], "resultado": round(x["receitas"] - x["despesas"], 2)})
    return render_template("fin_resultado.html", **_ctx_base("resultado"), mes=mes, anterior=ant, proximo=cartao_analise.somar_meses(mes, 1),
                           t=t, t_ant=t_ant, res=res, res_ant=res_ant, var_resultado=fl.variacao_pct(res, res_ant),
                           margem=round(res / t["receitas"] * 100, 1) if t["receitas"] else None,
                           linhas_rec=fl.linhas_categoria(rec, nomes, t["receitas"]), linhas_desp=fl.linhas_categoria(desp, nomes, t["receitas"] or t["despesas"]),
                           base_pct="da receita" if t["receitas"] else "das despesas", serie=serie, caixa_mes=t["saldo"])


@fin_bp.route("/fluxo")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def fluxo():
    n = int(request.args.get("meses")) if (request.args.get("meses") or "").isdigit() and int(request.args.get("meses")) in fl.HORIZONTES else 3
    saldo_param = _numero(request.args.get("saldo"))
    f, info = construir_fluxo(_org(), n, saldo_param)
    return render_template("fin_fluxo.html", **_ctx_base("fluxo"), f=f, n=n, horizontes=fl.HORIZONTES, info=info, saldo_digitado=request.args.get("saldo") or "")


@fin_bp.route("/impostos")
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def impostos():
    hoje = date.today()
    meus = {l["nome"] for l in db.listar_lembretes(_org(), g.usuario_atual["id"])}
    itens = []
    for ob in fl.OBRIGACOES:
        prox = fl.proxima_ocorrencia(ob, hoje)
        itens.append({**ob, "proxima": prox, "dias": (prox - hoje).days, "tem_lembrete": ob["nome"] in meus})
    return render_template("fin_impostos.html", **_ctx_base("impostos"), itens=sorted(itens, key=lambda i: i["dias"]), dias_antes=fl.DIAS_ANTES_LEMBRETE)


@fin_bp.route("/impostos/lembrete", methods=["POST"])
@login_required
@requer_organizacao
@requer_modulo(MODULO)
@requer_papel("super_admin", "admin_cliente")
def criar_lembrete():
    ob = fl.obrigacao(request.form.get("chave"))
    if not ob or ob["frequencia"] != "mensal":
        flash("Escolha uma obrigação mensal da lista.", "erro")
    elif ob["nome"] in {l["nome"] for l in db.listar_lembretes(_org(), g.usuario_atual["id"])}:
        flash(f"Você já tem o lembrete \"{ob['nome']}\".", "erro")
    else:
        db.criar_lembrete(_org(), g.usuario_atual["id"], ob["nome"], ob["dia"], fl.DIAS_ANTES_LEMBRETE, None, False)
        flash(f"Lembrete criado: \"{ob['nome']}\". Você será avisado {fl.DIAS_ANTES_LEMBRETE} dias antes do dia {ob['dia']}, todo mês.", "ok")
    return redirect(url_for("fin.impostos"))
