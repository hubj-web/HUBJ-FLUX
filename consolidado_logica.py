# -*- coding: utf-8 -*-
"""Meu dinheiro total: soma família e empresas do mesmo cliente SEM contar em dobro o que só passou de um bolso para o outro.

Regra: uma transferência entre os espaços é eliminada do total na ponta que contou como receita ou despesa (pró-labore: sai das duas pontas;
distribuição de lucros: sai só da renda da família, porque o lucro já está no resultado da empresa). Aporte, empréstimo, devolução e reembolso nunca
entraram no resultado, então não há o que eliminar. O CAIXA, esse sim, é a soma direta (a transferência sai de um lado e entra no outro: dá zero)."""
from transferencias_logica import OPERACOES


def consolidar(espacos, transferencias):
    """espacos: [{id, nome, tipo, receitas, despesas, saldo (caixa do mês), saldo_contas}]; transferencias: as do mês [{operacao, valor, org_origem_id, org_destino_id}]."""
    ids = {e["id"] for e in espacos}
    int_rec = int_desp = 0.0
    por_operacao = {k: 0.0 for k in OPERACOES}
    for t in transferencias:
        op = OPERACOES.get(t["operacao"])
        if not op or t["org_origem_id"] not in ids or t["org_destino_id"] not in ids:
            continue
        v = float(t["valor"])
        por_operacao[t["operacao"]] += v
        if not op["fora_origem"]:
            int_desp += v
        if not op["fora_destino"]:
            int_rec += v
    linhas = [{**e, "resultado": round(e["receitas"] - e["despesas"], 2)} for e in espacos]
    rec, desp = sum(e["receitas"] for e in espacos), sum(e["despesas"] for e in espacos)
    total = {"receitas_brutas": round(rec, 2), "despesas_brutas": round(desp, 2), "internas_receitas": round(int_rec, 2), "internas_despesas": round(int_desp, 2),
             "receitas": round(rec - int_rec, 2), "despesas": round(desp - int_desp, 2), "resultado": round((rec - int_rec) - (desp - int_desp), 2),
             "caixa_mes": round(sum(e["saldo"] for e in espacos), 2), "saldo_contas": round(sum(e["saldo_contas"] for e in espacos), 2)}
    return {"linhas": linhas, "total": total, "por_operacao": {k: round(v, 2) for k, v in por_operacao.items()}}
