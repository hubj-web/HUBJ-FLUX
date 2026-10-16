# -*- coding: utf-8 -*-
"""Planejamento mensal: junta, mês a mês (mês de CAIXA, quando o dinheiro sai), o que já está
comprometido - gastos fixos/recorrentes + cartão - e quanto sobra da renda."""
import calendar
from datetime import date

from cartao_analise import somar_meses

PASSO = {"mensal": 1, "bimestral": 2, "trimestral": 3, "semestral": 6, "anual": 12}
ROTULO_FREQUENCIA = {"mensal": "todo mês", "bimestral": "a cada 2 meses", "trimestral": "a cada 3 meses",
                     "semestral": "a cada 6 meses", "anual": "uma vez por ano"}


def _n(mes):
    return int(mes[:4]) * 12 + int(mes[5:7]) - 1


def ocorre_no_mes(item, mes):
    """O gasto cai neste mês? Respeita o mês de início, o de término e a frequência."""
    if mes < item["mes_inicio"]:
        return False
    if item.get("mes_fim") and mes > item["mes_fim"]:
        return False
    return (_n(mes) - _n(item["mes_inicio"])) % PASSO[item["frequencia"]] == 0


def dia_efetivo(mes, dia):
    """Dia 31 em mês curto vence no último dia do mês."""
    return min(int(dia), calendar.monthrange(int(mes[:4]), int(mes[5:7]))[1])


def media_mensal(fixos):
    """Quanto os gastos ativos pesam por mês, em média (um anual de 1.200 pesa 100 por mês)."""
    return round(sum(float(g["valor"]) / PASSO[g["frequencia"]] for g in fixos if g.get("ativo", True)), 2)


def calcular_deslocamento(faturas):
    """Quantos meses depois do 'mês da fatura' ela vence (normalmente 1). Usa a fatura mais recente."""
    try:
        f = faturas[0]
        return max(0, _n(f["vencimento"].strftime("%Y-%m")) - _n(f["mes_referencia"]))
    except Exception:
        return 1


def visao_mensal(hoje, n, fixos, faturas, parcelas, renda_por_mes, renda_padrao, deslocamento=1, empresa_cartao_por_mes=None):
    """faturas: [{mes_referencia, total, vencimento}] já importadas; parcelas: saída de
    cartao_analise.projetar_parcelas (meses de FATURA). Devolve n meses a partir do mês de hoje."""
    mes0 = hoje.strftime("%Y-%m")
    caixa_faturas, empresa_contada = {}, set()
    for f in faturas:
        venc = f.get("vencimento")
        chave = venc.strftime("%Y-%m") if venc else somar_meses(f["mes_referencia"], deslocamento)
        d = caixa_faturas.setdefault(chave, {"total": 0.0, "previa": False, "empresa": 0.0})
        d["total"] += float(f["total"] or 0)
        if f["mes_referencia"] not in empresa_contada:  # a parte da empresa é por mês: não soma de novo se o mês vier em mais de uma linha
            empresa_contada.add(f["mes_referencia"])
            d["empresa"] += float((empresa_cartao_por_mes or {}).get(f["mes_referencia"], 0))
        d["previa"] = d["previa"] or bool(f.get("previa"))
    ultimo_caixa = max(caixa_faturas) if caixa_faturas else ""
    caixa_parcelas = {somar_meses(m["mes"], deslocamento): m for m in parcelas}

    meses = []
    for i in range(n):
        mes = somar_meses(mes0, i)
        itens = []
        for g in fixos:
            if not g.get("ativo", True) or not ocorre_no_mes(g, mes):
                continue
            if g.get("no_cartao") and ultimo_caixa and mes <= ultimo_caixa:
                continue  # já está dentro da fatura importada deste mês: contar de novo seria dobrar
            itens.append({"id": g.get("id"), "nome": g["nome"], "valor": float(g["valor"]), "dia": dia_efetivo(mes, g["dia_mes"]),
                          "estimado": bool(g.get("estimado")), "no_cartao": bool(g.get("no_cartao")), "destino": g.get("destino_empresa_id")})
        itens.sort(key=lambda x: (x["dia"], x["nome"]))
        total_fixos = round(sum(x["valor"] for x in itens), 2)

        if mes in caixa_faturas:
            cartao = {"total": round(caixa_faturas[mes]["total"], 2), "origem": "previa" if caixa_faturas[mes]["previa"] else "fatura", "itens": []}
        elif mes in caixa_parcelas:
            cartao = {"total": round(caixa_parcelas[mes]["total"], 2), "origem": "parcelas", "itens": caixa_parcelas[mes]["itens"]}
        else:
            cartao = {"total": 0.0, "origem": None, "itens": []}

        da_empresa = sum(x["valor"] for x in itens if x.get("destino"))
        if cartao["origem"] in ("fatura", "previa"):
            da_empresa += caixa_faturas[mes].get("empresa", 0.0)
        elif cartao["origem"] == "parcelas":
            da_empresa += sum(i["valor"] for i in cartao["itens"] if i.get("destino"))
        renda = renda_por_mes.get(mes) or renda_padrao
        renda = float(renda) if renda else None
        comprometido = round(total_fixos + cartao["total"], 2)
        livre = round(renda - comprometido, 2) if renda is not None else None
        pct = round(comprometido / renda * 100) if renda else None
        nivel = None if pct is None else ("verde" if pct < 70 else "amarelo" if pct < 90 else "vermelho")
        if livre is not None and livre < 0:
            nivel = "vermelho"
        meses.append({"mes": mes, "renda": renda, "fixos": itens, "total_fixos": total_fixos, "cartao": cartao,
                      "comprometido": comprometido, "livre": livre, "pct": pct, "nivel": nivel, "da_empresa": round(da_empresa, 2)})
    return meses
