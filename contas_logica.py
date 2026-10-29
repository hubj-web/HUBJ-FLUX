# -*- coding: utf-8 -*-
"""Contas a pagar e a receber: regras puras (datas, parcelas, situação), sem banco."""
import calendar
from datetime import date

SITUACOES_LISTA = ("abertos", "vencidos", "pagos", "cancelados", "todos")
ROTULO_SITUACAO = {"pago": "Paga", "cancelado": "Cancelada", "vencido": "Vencida", "vence_hoje": "Vence hoje", "a_vencer": "A vencer"}


def somar_meses(d, n):
    """Soma n meses mantendo o dia; se o mês não tem esse dia, usa o último (31/01 + 1 mês = 28/02)."""
    m = d.month - 1 + n
    ano, mes = d.year + m // 12, m % 12 + 1
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def gerar_parcelas(vencimento, n):
    """[(número, vencimento)] uma por mês, sempre a partir do vencimento original (não acumula o ajuste do fim de mês)."""
    return [(i + 1, somar_meses(vencimento, i)) for i in range(n)]


def situacao(status, vencimento, hoje):
    if status in ("pago", "cancelado"):
        return status
    if vencimento < hoje:
        return "vencido"
    return "vence_hoje" if vencimento == hoje else "a_vencer"


def dias_para_vencer(vencimento, hoje):
    """Positivo: faltam dias; negativo: atrasada há N dias."""
    return (vencimento - hoje).days


def descricao_da_parcela(descricao, numero, total):
    return descricao if total <= 1 else f"{descricao} ({numero}/{total})"
