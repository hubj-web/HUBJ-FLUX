# -*- coding: utf-8 -*-
"""Resultado e fluxo de caixa: consultas ao banco."""
import db
from db import query_all


def receitas_por_categoria_mes(organizacao_id, mes):
    """Receitas do mês por categoria. O que é só movimento de caixa entre família e empresa (aporte, empréstimo...) fica de fora."""
    rows = query_all(
        """SELECT categoria_id, SUM(valor) AS total FROM lancamentos
           WHERE organizacao_id = %s AND tipo = 'receita' AND NOT fora_do_resultado AND to_char(data, 'YYYY-MM') = %s GROUP BY categoria_id""",
        (organizacao_id, mes))
    return {r["categoria_id"]: float(r["total"]) for r in rows}


def nomes_categorias(organizacao_id):
    return {r["id"]: r["nome"] for r in query_all("SELECT id, nome FROM categorias WHERE organizacao_id = %s", (organizacao_id,))}


def saldo_das_contas(organizacao_id):
    """(saldo somado das contas bancárias ativas, quantas são). O saldo de cada conta é o inicial mais os lançamentos ligados a ela."""
    contas = db.listar_contas_bancarias(organizacao_id)
    return round(sum(db.saldo_atual_conta(c["id"], organizacao_id) or 0.0 for c in contas), 2), len(contas)


def titulos_abertos(organizacao_id):
    return query_all("SELECT tipo, valor, vencimento FROM titulos WHERE organizacao_id = %s AND status = 'aberto'", (organizacao_id,))
