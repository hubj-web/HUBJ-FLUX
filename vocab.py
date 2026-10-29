# -*- coding: utf-8 -*-
"""Palavras que mudam conforme o espaço em que a pessoa está (Família ou Empresa)."""

VOCAB = {
    "familia": {"rotulo": "Família", "gastos_mes": "Gastos da família no mês", "saldo_mes": "Saldo do mês"},
    "empresa": {"rotulo": "Empresa", "gastos_mes": "Saídas do mês", "saldo_mes": "Saldo do caixa"},
}


def para(tipo):
    """Os textos do espaço. Qualquer tipo desconhecido usa os da família (o que o app sempre mostrou)."""
    return VOCAB.get(tipo, VOCAB["familia"])
