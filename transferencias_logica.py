# -*- coding: utf-8 -*-
"""Transferências entre a Família e a Empresa do mesmo cliente: as operações e as regras de como cada ponta conta.

'fora_*' = a ponta só mexe no CAIXA (saldo): não conta como gasto nem como receita no Mês, no Controle e nos Relatórios."""
from collections import OrderedDict

OPERACOES = OrderedDict([
    ("pro_labore", {"nome": "Pró-labore", "de": "empresa", "para": "familia", "fora_origem": False, "fora_destino": False,
                    "ajuda": "A empresa paga o seu salário de sócio. É despesa da empresa e renda da família.",
                    "cat_origem": ["Folha e pró-labore", "Pró-labore"], "cat_destino": ["Salário", "Pró-labore"]}),
    ("distribuicao_lucros", {"nome": "Distribuição de lucros", "de": "empresa", "para": "familia", "fora_origem": True, "fora_destino": False,
                             "ajuda": "A empresa distribui lucro para o sócio. Não é despesa da empresa, mas é renda da família.",
                             "cat_origem": ["Distribuição de lucros"], "cat_destino": ["Distribuição de lucros"]}),
    ("aporte", {"nome": "Aporte do sócio (capital)", "de": "familia", "para": "empresa", "fora_origem": True, "fora_destino": True,
                "ajuda": "O sócio coloca dinheiro na empresa como capital. Não é gasto da família nem receita da empresa.",
                "cat_origem": ["Aporte na empresa"], "cat_destino": ["Aporte do sócio"]}),
    ("emprestimo_socio", {"nome": "Empréstimo do sócio à empresa", "de": "familia", "para": "empresa", "fora_origem": True, "fora_destino": True,
                          "ajuda": "O sócio empresta dinheiro à empresa, que vai devolver depois. Não é gasto nem receita.",
                          "cat_origem": ["Empréstimo à empresa"], "cat_destino": ["Empréstimo do sócio"]}),
    ("devolucao_emprestimo", {"nome": "Devolução do empréstimo ao sócio", "de": "empresa", "para": "familia", "fora_origem": True, "fora_destino": True,
                              "ajuda": "A empresa devolve ao sócio um empréstimo. Não é despesa nem renda.",
                              "cat_origem": ["Devolução de empréstimo ao sócio"], "cat_destino": ["Devolução de empréstimo da empresa"]}),
    ("reembolso", {"nome": "Reembolso de despesa paga pelo sócio", "de": "empresa", "para": "familia", "fora_origem": True, "fora_destino": True,
                   "ajuda": "A empresa devolve ao sócio uma despesa dela que ele pagou do próprio bolso. Não é renda da família.",
                   "cat_origem": ["Reembolso ao sócio"], "cat_destino": ["Reembolso da empresa"]}),
])


def operacao(chave):
    return OPERACOES.get(chave)


def descricao_padrao(chave, data):
    op = OPERACOES[chave]
    return f"{op['nome']} {data.strftime('%m/%Y')}" if chave == "pro_labore" else op["nome"]


def resumo(linhas):
    """Totais por operação e quanto a empresa ainda deve ao sócio de empréstimo. linhas: dicionários com 'operacao' e 'valor'."""
    por = {chave: 0.0 for chave in OPERACOES}
    for l in linhas:
        if l["operacao"] in por:
            por[l["operacao"]] += float(l["valor"])
    por = {k: round(v, 2) for k, v in por.items()}
    return {"por_operacao": por, "emprestimo_em_aberto": round(por["emprestimo_socio"] - por["devolucao_emprestimo"], 2)}
