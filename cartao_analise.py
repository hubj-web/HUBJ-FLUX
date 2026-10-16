# -*- coding: utf-8 -*-
"""Regras de análise do cartão: faturas agrupadas por mês e projeção das parcelas
que já estão compradas e vão cair nos meses seguintes."""
from datetime import date

from dateutil.relativedelta import relativedelta


MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(mes):
    """'2026-02' -> 'fev/2026'."""
    return f"{MESES_ABREV[int(mes[5:7]) - 1]}/{mes[:4]}"


def somar_meses(mes, n):
    """'2026-02' + 3 -> '2026-05'."""
    base = date(int(mes[:4]), int(mes[5:7]), 1) + relativedelta(months=n)
    return base.strftime("%Y-%m")


def agrupar_faturas_por_mes(faturas):
    """Junta as faturas (uma por cartão/pessoa) na fatura completa do mês."""
    meses = {}
    for f in faturas:
        m = meses.setdefault(f["mes_referencia"], {
            "mes_referencia": f["mes_referencia"], "total": 0.0, "n_transacoes": 0,
            "vencimento": f["vencimento"], "cartoes": []})
        m["total"] += float(f["valor_total"] or 0)
        m["n_transacoes"] += int(f["n_transacoes"] or 0)
        m["cartoes"].append(f)
    return sorted(meses.values(), key=lambda m: m["mes_referencia"], reverse=True)


def regra_para(regras, descricao):
    """Primeira regra cujo texto aparece na descrição; as mais específicas (textos maiores) ganham."""
    desc = (descricao or "").upper()
    for r in sorted(regras, key=lambda r: -len(r["padrao"] or "")):
        if r["padrao"] and r["padrao"].upper() in desc:
            return r
    return None


def projetar_parcelas(linhas, ultimo_mes, compromissos=None):
    """linhas: compras parceladas já importadas (qualquer parcela, de qualquer fatura).
    Para cada compra, pega a parcela mais recente que apareceu e projeta as que faltam,
    um mês por parcela. Só entram meses DEPOIS da última fatura importada (os anteriores
    já estão nas próprias faturas). Compra marcada como 'não projetar' em qualquer parcela
    fica de fora. compromissos: compras parceladas cadastradas à mão, que só valem enquanto
    sua 1ª parcela ainda não chegou a nenhuma fatura importada.
    Devolve [{mes, total, itens}] em ordem cronológica."""
    compras = {}
    # 'não projetar' vale para o mesmo fornecedor + mesma pessoa + mesmo total de parcelas,
    # mesmo que o valor de alguma parcela tenha sido corrigido e a compra tenha se dividido em grupos
    ignorados = {(r.get("pessoa_id"), (r["descricao"] or "").strip().upper(), int(r["parcela_total"]))
                 for r in linhas if r.get("nao_projetar")}
    for r in linhas:
        chave = (r.get("pessoa_id"), (r["descricao"] or "").strip().upper(),
                 int(r["parcela_total"]), round(float(r["valor"]), 2))
        c = compras.setdefault(chave, {"ocorrencias": {}, "ignorar": False})
        c["ignorar"] = c["ignorar"] or bool(r.get("nao_projetar"))
        info = c["ocorrencias"].setdefault((int(r["parcela_atual"]), r["mes_referencia"]),
                                           {"qtd": 0, "descricao": r["descricao"], "pessoa": r.get("pessoa_nome"), "id": r.get("id"),
                                            "destino": r.get("destino_empresa_id")})
        info["qtd"] += 1  # duas compras idênticas no mesmo mês contam as duas

    # a prévia da fatura trunca o nome da loja (ex.: "MP INTERCELLUDI" x "MP INTERCELLUDIL"): junta o que for a mesma compra
    por_base = {}
    for chave in sorted(compras, key=lambda k: -len(k[1])):
        pessoa, desc, total, valor = chave
        base = por_base.setdefault((pessoa, total, valor), [])
        alvo = next((k for k in base if len(desc) >= 8 and k[1].startswith(desc)), None)
        if alvo is None:
            base.append(chave)
            continue
        destino = compras[alvo]
        destino["ignorar"] = destino["ignorar"] or compras[chave]["ignorar"]
        for ocorr, info in compras[chave]["ocorrencias"].items():
            if ocorr in destino["ocorrencias"]:
                destino["ocorrencias"][ocorr]["qtd"] = max(destino["ocorrencias"][ocorr]["qtd"], info["qtd"])
            else:
                destino["ocorrencias"][ocorr] = info
        del compras[chave]

    meses = {}

    def somar(mes, item):
        m = meses.setdefault(mes, {"mes": mes, "total": 0.0, "itens": []})
        m["total"] += item["valor"]
        m["itens"].append(item)

    for (pessoa_id, descricao, total, valor), c in compras.items():
        if c["ignorar"] or (pessoa_id, descricao, total) in ignorados:
            continue
        (parcela, mes_ref), info = max(c["ocorrencias"].items(), key=lambda kv: kv[0])
        for k in range(1, total - parcela + 1):
            mes = somar_meses(mes_ref, k)
            if mes <= ultimo_mes:
                continue
            nome = max((i["descricao"] or "" for i in c["ocorrencias"].values()), key=len)  # a prévia trunca o nome: mostra o mais completo
            somar(mes, {"descricao": nome, "parcela": f"{parcela + k}/{total}",
                        "valor": valor * info["qtd"], "pessoa": info["pessoa"], "compra_id": info["id"], "destino": info.get("destino")})

    for k in compromissos or []:
        if ultimo_mes and k["mes_inicial"] <= ultimo_mes:
            continue  # já chegou às faturas importadas: os dados reais assumem
        n, valor = int(k["num_parcelas"]), float(k["valor_parcela"])
        for i in range(n):
            somar(somar_meses(k["mes_inicial"], i), {"descricao": k["descricao"], "parcela": f"{i + 1}/{n}",
                                                     "valor": valor, "pessoa": k.get("pessoa_nome"), "manual_id": k["id"]})

    saida = [meses[m] for m in sorted(meses)]
    for m in saida:
        m["total"] = round(m["total"], 2)
        m["itens"].sort(key=lambda i: -i["valor"])
    return saida
