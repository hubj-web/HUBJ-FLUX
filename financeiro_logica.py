# -*- coding: utf-8 -*-
"""Resultado do mês, fluxo de caixa previsto e calendário de obrigações: regras puras, sem banco."""
import calendar
from datetime import date

from cartao_analise import somar_meses

HORIZONTES = (3, 6, 12)

# Datas conferidas em outubro/2026 (Receita Federal/Comitê Gestor do Simples, Ministério do Trabalho e contabilidade). NÃO substituem o contador.
# O app NÃO calcula o que acontece quando o dia cai em fim de semana ou feriado (as fontes divergem no DAS): sempre conferir a data da guia emitida.
OBRIGACOES = [
    {"chave": "das", "nome": "DAS (Simples Nacional e MEI)", "frequencia": "mensal", "dia": 20, "quem": "MEI e empresas do Simples Nacional",
     "ajuda": "Vence no dia 20 do mês seguinte ao da competência. Se o dia 20 cair em fim de semana ou feriado, a data muda: confira SEMPRE a data impressa na guia que você emitiu."},
    {"chave": "fgts", "nome": "FGTS Digital (funcionários)", "frequencia": "mensal", "dia": 20, "quem": "Empresas com funcionários",
     "ajuda": "Vence no dia 20 do mês seguinte. Se o dia 20 não for dia útil, a data é antecipada para o dia útil anterior. O pagamento é só por Pix."},
    {"chave": "defis", "nome": "DEFIS (declaração anual)", "frequencia": "anual", "mes": 3, "dia": 31, "quem": "Microempresas e empresas de pequeno porte do Simples (não é do MEI)",
     "ajuda": "Declaração entregue até 31 de março do ano seguinte, mesmo sem faturamento. O atraso gera multa."},
    {"chave": "dasn", "nome": "DASN-SIMEI (declaração anual do MEI)", "frequencia": "anual", "mes": 5, "dia": 31, "quem": "MEI",
     "ajuda": "Declaração do faturamento do ano anterior, entregue até 31 de maio, mesmo sem faturamento. O atraso gera multa mínima de R$ 50,00."},
]
DIAS_ANTES_LEMBRETE = 5   # avisa com folga, para dar tempo de emitir a guia e conferir a data


def obrigacao(chave):
    return next((o for o in OBRIGACOES if o["chave"] == chave), None)


def _data_segura(ano, mes, dia):
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def proxima_ocorrencia(ob, hoje):
    """A próxima data NOMINAL da obrigação (sem ajustar fim de semana ou feriado)."""
    if ob["frequencia"] == "mensal":
        d = _data_segura(hoje.year, hoje.month, ob["dia"])
        if d >= hoje:
            return d
        prox = somar_meses(hoje.strftime("%Y-%m"), 1)
        return _data_segura(int(prox[:4]), int(prox[5:]), ob["dia"])
    d = _data_segura(hoje.year, ob["mes"], ob["dia"])
    return d if d >= hoje else _data_segura(hoje.year + 1, ob["mes"], ob["dia"])


def variacao_pct(atual, anterior):
    """Quanto mudou em relação ao mês anterior, em %. None se não há como comparar (anterior zerado)."""
    if not anterior:
        return None
    return round((atual - anterior) / abs(anterior) * 100, 1)


def linhas_categoria(totais_por_categoria, nomes, base):
    """{categoria_id ou None: valor} -> linhas com nome, valor e % da base, da maior para a menor."""
    linhas = []
    for cid, v in totais_por_categoria.items():
        if abs(v) < 0.005:
            continue
        nome = "Sem categoria" if cid is None else nomes.get(cid, "Categoria apagada")
        linhas.append({"nome": nome, "valor": round(float(v), 2), "pct": round(float(v) / base * 100, 1) if base else None})
    return sorted(linhas, key=lambda l: -l["valor"])


def montar_fluxo(hoje, n, saldo_inicial, titulos, plan_meses, vencimento_fatura_por_mes=None):
    """Projeta o caixa dos próximos n meses.
    titulos: contas EM ABERTO [{tipo 'pagar'|'receber', valor, vencimento}]. plan_meses: os meses do planejamento mensal (gastos fixos e cartão).
    No mês atual só entra o que ainda vai vencer de hoje em diante (o que já passou já está no saldo); conta atrasada é tratada como se fosse
    cair neste mês. O que vence depois do horizonte fica de fora e é informado à parte."""
    mes0 = hoje.strftime("%Y-%m")
    meses = [{"mes": somar_meses(mes0, i), "receber": 0.0, "pagar": 0.0, "fixos": 0.0, "cartao": 0.0} for i in range(n)]
    por_mes = {m["mes"]: m for m in meses}
    depois = {"receber": 0.0, "pagar": 0.0}
    for t in titulos:
        venc, v = t["vencimento"], float(t["valor"])
        chave = venc.strftime("%Y-%m") if venc >= hoje else mes0
        if chave in por_mes:
            por_mes[chave][t["tipo"]] += v
        elif chave > meses[-1]["mes"]:
            depois[t["tipo"]] += v
    plan = {p["mes"]: p for p in plan_meses}
    venc_fatura = vencimento_fatura_por_mes or {}
    for m in meses:
        p = plan.get(m["mes"])
        if not p:
            continue
        if m["mes"] == mes0:
            m["fixos"] = sum(float(i["valor"]) for i in p["fixos"] if i["dia"] >= hoje.day)
            vf = venc_fatura.get(mes0)
            m["cartao"] = 0.0 if (vf is not None and vf < hoje) else float(p["cartao"]["total"])
        else:
            m["fixos"], m["cartao"] = float(p["total_fixos"]), float(p["cartao"]["total"])
    saldo = round(float(saldo_inicial), 2)
    for m in meses:
        m["entradas"] = round(m["receber"], 2)
        m["saidas"] = round(m["pagar"] + m["fixos"] + m["cartao"], 2)
        m["saldo_mes"] = round(m["entradas"] - m["saidas"], 2)
        saldo = round(saldo + m["saldo_mes"], 2)
        m["saldo_final"] = saldo
        for k in ("receber", "pagar", "fixos", "cartao"):
            m[k] = round(m[k], 2)
    return {"meses": meses, "saldo_inicial": round(float(saldo_inicial), 2), "depois": {k: round(v, 2) for k, v in depois.items()},
            "primeiro_negativo": next((m for m in meses if m["saldo_final"] < 0), None), "menor_saldo": min(m["saldo_final"] for m in meses)}
