# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, g, request

import avisos_contas
import categorizacao_db
import contas_db
from cartao_analise import rotulo_mes
from financeiro import alerta_caixa
from trilha import estado as estado_trilha
import db
import modulos
import empresa as empresa_mod
import alertas
import quadro_mes
from auth import login_required
import regras_negocio
from mensal import _carregar as carregar_planejamento

inicio_bp = Blueprint("inicio", __name__)


@inicio_bp.route("/")
@login_required
def index():
    usuario = g.usuario_atual
    organizacao = db.buscar_organizacao(usuario["organizacao_id"])

    if usuario["organizacao_id"] is None:
        return render_template("inicio_super_admin.html", usuario=usuario)

    mes_referencia = request.args.get("mes") or date.today().strftime("%Y-%m")
    ref_date = date.fromisoformat(mes_referencia + "-01")
    mes_anterior = (ref_date - relativedelta(months=1)).strftime("%Y-%m")
    mes_seguinte = (ref_date + relativedelta(months=1)).strftime("%Y-%m")

    alertas.disparar_lembretes(usuario["organizacao_id"])  # idempotente: não repete no mesmo dia
    totais = db.totais_mes(usuario["organizacao_id"], mes_referencia)
    ultimos = db.ultimos_lancamentos(usuario["organizacao_id"], limite=5)
    frase_saldo = regras_negocio.frase_saldo_mes(totais["saldo"])
    prefs = db.buscar_preferencias(usuario["organizacao_id"])
    setup_concluido = bool(prefs and prefs.get("setup_concluido"))
    reservado_metas = db.total_reservado_metas(usuario["organizacao_id"])
    saldo_livre = totais["saldo"] - reservado_metas
    acertos_empresas = []
    if prefs and prefs.get("modulo_empresa"):
        nomes = {e["id"]: e["nome"] for e in db.listar_empresas(usuario["organizacao_id"], apenas_ativas=False)}
        consolidado = empresa_mod.consolidar(db.acerto_itens(usuario["organizacao_id"]), db.listar_acertos(usuario["organizacao_id"]), nomes)
        acertos_empresas = [s for s in consolidado.values() if abs(s["saldo"]) >= 0.005]

    # planejado x realizado da FAMÍLIA, a mesma conta do Controle
    org_id = usuario["organizacao_id"]
    planejado = {r["categoria_id"]: float(r["valor_limite"]) for r in db.listar_planejamento_mes(org_id, mes_referencia)}
    realizado = db.realizado_por_categoria_mes(org_id, mes_referencia, incluir_sem_categoria=True)
    nomes = {c["id"]: c["nome"] for c in db.listar_categorias(org_id)}
    quadro = quadro_mes.montar_quadro(planejado, realizado, nomes)
    renda_prevista = db.renda_planejada_por_mes(org_id, mes_referencia, mes_referencia).get(mes_referencia) \
        or (float(prefs["renda_mensal"]) if prefs and prefs.get("renda_mensal") else None)
    comprometido = None  # fixos + parcelas + fatura: só faz sentido do mês atual para frente
    if mes_referencia >= date.today().strftime("%Y-%m"):
        comprometido = next((m for m in carregar_planejamento(org_id, 12)["meses"] if m["mes"] == mes_referencia and m["comprometido"] > 0), None)

    try:
        avisos_contas.disparar(org_id)
    except Exception:  # um aviso a mais nunca pode derrubar o Mês
        try:
            db.get_conn().rollback()
        except Exception:
            pass
    sem_categoria = None
    if usuario["papel"] in ("super_admin", "admin_cliente"):
        try:
            cob = categorizacao_db.cobertura(org_id)
            if cob["pct_sem"] >= 20 and cob["sem"] >= 100:
                sem_categoria = cob
        except Exception:
            try:
                db.get_conn().rollback()
            except Exception:
                pass
    trilha = None
    if usuario["papel"] in ("super_admin", "admin_cliente") and modulos.modulo_ativo(org_id, "trilha"):
        try:
            t, _ = estado_trilha(org_id)
            trilha = t if t["total"] and t["feitos"] < t["total"] else None
        except Exception:
            try:
                db.get_conn().rollback()
            except Exception:
                pass
    caixa_negativo = None
    if usuario["papel"] in ("super_admin", "admin_cliente") and modulos.modulo_ativo(org_id, "resultado_caixa"):
        try:
            neg = alerta_caixa(org_id)
            caixa_negativo = {**neg, "rotulo": rotulo_mes(neg["mes"])} if neg else None
        except Exception:  # um aviso a mais nunca pode derrubar o Mês
            try:
                db.get_conn().rollback()
            except Exception:
                pass
    contas_resumo = contas_db.resumo_titulos(org_id, date.today()) if modulos.modulo_ativo(org_id, "contas_pagar_receber") else None

    return render_template(
        "inicio.html", trilha=trilha, sem_categoria=sem_categoria, caixa_negativo=caixa_negativo, contas_resumo=contas_resumo, usuario=usuario, organizacao=organizacao, quadro=quadro, renda_prevista=renda_prevista, comprometido=comprometido,
        mes_referencia=mes_referencia, mes_anterior=mes_anterior, mes_seguinte=mes_seguinte,
        totais=totais, ultimos=ultimos, frase_saldo=frase_saldo, setup_concluido=setup_concluido,
        reservado_metas=reservado_metas, saldo_livre=saldo_livre, acertos_empresas=acertos_empresas,
    )
