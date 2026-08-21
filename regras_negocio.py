# -*- coding: utf-8 -*-
"""Regras de negócio independentes de tela específica."""
from datetime import date
from dateutil.relativedelta import relativedelta


def calcular_periodo_fatura(dia_fechamento, data_referencia=None):
    hoje = data_referencia or date.today()
    if hoje.day <= dia_fechamento:
        fim = hoje.replace(day=dia_fechamento)
        inicio = (fim - relativedelta(months=1)) + relativedelta(days=1)
    else:
        inicio = hoje.replace(day=dia_fechamento) + relativedelta(days=1)
        fim = inicio + relativedelta(months=1) - relativedelta(days=1)
    return inicio, fim


def calcular_semaforo(valor_realizado, valor_planejado):
    if not valor_planejado or valor_planejado <= 0:
        return "sem_planejamento", "cinza"
    pct = valor_realizado / valor_planejado
    if pct < 0.80:
        return "dentro_do_limite", "verde"
    if pct < 1.00:
        return "atencao", "amarelo"
    return "estourado", "vermelho"


def _fmt_moeda(v):
    return f"R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def frase_saldo_mes(saldo):
    if saldo >= 0:
        return f"Você ainda tem {_fmt_moeda(saldo)} disponíveis este mês."
    return f"Atenção: você já gastou {_fmt_moeda(saldo)} a mais do que ganhou este mês."


def frase_categoria_mais_cara(nome_categoria, valor, total_despesas):
    if not total_despesas:
        return None
    pct = round((valor / total_despesas) * 100)
    return f"Sua maior categoria foi {nome_categoria} ({pct}%)."


PERCENTUAIS_SUGERIDOS_CATEGORIA = {
    "Moradia": 0.30, "Alimentação": 0.20, "Transporte": 0.10, "Saúde": 0.05,
    "Educação": 0.05, "Lazer": 0.10, "Vestuário": 0.05, "Outros": 0.10,
}


def sugerir_limites_por_renda(renda_mensal):
    return {cat: round(renda_mensal * pct, 2) for cat, pct in PERCENTUAIS_SUGERIDOS_CATEGORIA.items()}


def calcular_parcela_com_juros(valor_total, num_parcelas, taxa_juros_mensal_pct):
    """Tabela Price - parcela fixa com juros compostos."""
    i = taxa_juros_mensal_pct / 100
    return round(valor_total * i / (1 - (1 + i) ** -num_parcelas), 2)
