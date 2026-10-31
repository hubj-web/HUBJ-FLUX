# -*- coding: utf-8 -*-
"""Trilha guiada: detecção dos passos já feitos e marcas manuais."""
from datetime import date

import categorizacao_db
import db
import financeiro_logica as fl
from db import execute, query_all, query_one


def _existe(sql, params):
    return query_one(f"SELECT EXISTS ({sql}) AS ok", params)["ok"]


def tem_empresa(organizacao_id):
    """O cliente deste espaço tem algum espaço de empresa?"""
    return _existe("SELECT 1 FROM organizacoes e JOIN organizacoes o ON o.cliente_id = e.cliente_id WHERE o.id = %s AND e.tipo = 'empresa' AND e.cliente_id IS NOT NULL", (organizacao_id,))


def feitos_auto(organizacao_id):
    """O que o app consegue detectar sozinho, olhando os dados do espaço."""
    hoje_mes = date.today().strftime("%Y-%m")
    cob = categorizacao_db.cobertura(organizacao_id)
    contas = _existe("SELECT 1 FROM contas_bancarias WHERE organizacao_id = %s AND ativa = true", (organizacao_id,))
    nomes_obrigacoes = [o["nome"] for o in fl.OBRIGACOES if o["frequencia"] == "mensal"]
    return {
        "contas": contas, "contas_pj": contas,
        "lancar": query_one("SELECT COUNT(*) AS n FROM lancamentos WHERE organizacao_id = %s", (organizacao_id,))["n"] >= 5,
        "cartao": _existe("SELECT 1 FROM faturas f JOIN cartoes c ON c.id = f.cartao_id WHERE c.organizacao_id = %s", (organizacao_id,)),
        "categorizar": cob["n"] > 0 and cob["pct_sem"] < 20,
        "planejar": _existe("SELECT 1 FROM planejamentos WHERE organizacao_id = %s AND mes_referencia >= %s", (organizacao_id, hoje_mes)),
        "parceiros": _existe("SELECT 1 FROM parceiros WHERE organizacao_id = %s", (organizacao_id,)),
        "contas_pagar": _existe("SELECT 1 FROM titulos WHERE organizacao_id = %s AND tipo = 'pagar'", (organizacao_id,)),
        "contas_receber": _existe("SELECT 1 FROM titulos WHERE organizacao_id = %s AND tipo = 'receber'", (organizacao_id,)),
        "prolabore": _existe("SELECT 1 FROM transferencias WHERE operacao = 'pro_labore' AND (org_origem_id = %s OR org_destino_id = %s)", (organizacao_id, organizacao_id)),
        "prolabore_familia": _existe("SELECT 1 FROM transferencias WHERE operacao = 'pro_labore' AND (org_origem_id = %s OR org_destino_id = %s)", (organizacao_id, organizacao_id)),
        "impostos": _existe("SELECT 1 FROM lembretes_vencimento WHERE organizacao_id = %s AND nome = ANY(%s)", (organizacao_id, nomes_obrigacoes)),
    }


def marcas(organizacao_id):
    return {r["passo"] for r in query_all("SELECT passo FROM trilha_marcas WHERE organizacao_id = %s", (organizacao_id,))}


def marcar(organizacao_id, passo, usuario_id):
    execute("INSERT INTO trilha_marcas (organizacao_id, passo, marcado_por) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (organizacao_id, passo, usuario_id))


def desmarcar(organizacao_id, passo):
    execute("DELETE FROM trilha_marcas WHERE organizacao_id = %s AND passo = %s", (organizacao_id, passo))
