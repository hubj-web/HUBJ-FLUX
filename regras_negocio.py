# -*- coding: utf-8 -*-
"""Regras de negócio do HUB-J FLUX, independentes de tela específica -
extraídas e adaptadas do documento de especificação técnica (seção 5).
Funções puras, fáceis de testar isoladamente."""
from datetime import date
from dateutil.relativedelta import relativedelta


def calcular_periodo_fatura(dia_fechamento, data_referencia=None):
    """Dado o dia de fechamento de um cartão, devolve (inicio, fim) do
    período da fatura ATUAL que cobre `data_referencia` (hoje, por padrão).

    Regra: a fatura vai do dia (fechamento+1) do mês anterior até o dia
    (fechamento) do mês atual - ex: fechamento dia 15, hoje 10/06 ->
    fatura atual 16/05 a 15/06. Se hoje for 20/06, a fatura atual já é
    16/06 a 15/07 (a fatura de maio-junho já fechou)."""
    hoje = data_referencia or date.today()
    if hoje.day <= dia_fechamento:
        fim = hoje.replace(day=dia_fechamento)
        inicio = (fim - relativedelta(months=1)) + relativedelta(days=1)
    else:
        inicio = hoje.replace(day=dia_fechamento) + relativedelta(days=1)
        fim = inicio + relativedelta(months=1) - relativedelta(days=1)
    return inicio, fim


def calcular_semaforo(valor_realizado, valor_planejado):
    """Estado do semáforo de orçamento (usado em Controle/Planejamento,
    quando esses módulos existirem). Retorna (estado, classe_css)."""
    if not valor_planejado or valor_planejado <= 0:
        return "sem_limite", "cinza"
    pct = valor_realizado / valor_planejado
    if pct < 0.80:
        return "dentro_do_limite", "verde"
    if pct < 1.00:
        return "atencao", "amarelo"
    return "estourado", "vermelho"


def _fmt_moeda(v):
    return f"R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def frase_saldo_mes(saldo):
    """Frase automática pro dashboard do Início, com base no saldo do mês."""
    if saldo >= 0:
        return f"Você ainda tem {_fmt_moeda(saldo)} disponíveis este mês."
    return f"Atenção: você já gastou {_fmt_moeda(saldo)} a mais do que ganhou este mês."


def frase_resumo_mes_encerrado(resultado):
    """Frase automática pro Fechamento Mensal (quando essa tela existir)."""
    if resultado > 0:
        return f"Parabéns! Você guardou {_fmt_moeda(resultado)} este mês."
    if resultado < 0:
        return f"Você gastou {_fmt_moeda(resultado)} a mais do que ganhou este mês."
    return "Suas receitas e despesas empataram este mês."


def frase_categoria_mais_cara(nome_categoria, valor, total_despesas):
    if not total_despesas:
        return None
    pct = round((valor / total_despesas) * 100)
    return f"Sua maior categoria foi {nome_categoria} ({pct}%)."


# Percentuais sugeridos de orçamento por categoria, com base na renda mensal
# informada no onboarding (quando essa etapa existir). Referência: seção 5.5
# do documento de especificação técnica.
PERCENTUAIS_SUGERIDOS_CATEGORIA = {
    "Moradia": 0.30,
    "Alimentação": 0.20,
    "Transporte": 0.10,
    "Saúde": 0.05,
    "Educação": 0.05,
    "Lazer": 0.10,
    "Vestuário": 0.05,
    "Outros": 0.10,
}


def sugerir_limites_por_renda(renda_mensal):
    """{ 'Moradia': 1500.0, 'Alimentação': 1000.0, ... } para renda=5000."""
    return {cat: round(renda_mensal * pct, 2) for cat, pct in PERCENTUAIS_SUGERIDOS_CATEGORIA.items()}
