# -*- coding: utf-8 -*-
"""Acerto entre a Família e as empresas. Regra única:

  quem PAGOU (dono do cartão ou da conta; vazio = Família)  x  PARA QUEM foi o gasto (vazio = Família)

Quando os dois são diferentes, nasce uma pendência. Saldo > 0: a empresa deve à Família;
saldo < 0: a Família deve à empresa. Os acertos registrados (reembolso, compensação) abatem o saldo."""
from collections import defaultdict
from decimal import Decimal


def _num(v):
    return float(v) if v is not None else 0.0


def efeito_do_item(pagador, destino, valor):
    """(empresa_id, valor com sinal) ou None se não gera pendência entre Família e empresa."""
    if pagador is None and destino is not None:
        return destino, _num(valor)            # a Família pagou o que é da empresa: a empresa deve
    if pagador is not None and destino is None:
        return pagador, -_num(valor)           # a empresa pagou o que é da Família: a Família deve
    return None                                 # mesmo lado, ou entre duas empresas: fora do escopo


def frase_saldo(nome, saldo):
    if abs(saldo) < 0.005:
        return f"Tudo acertado com {nome}"
    return f"{nome} deve à Família" if saldo > 0 else f"A Família deve a {nome}"


def consolidar(itens, acertos, nomes):
    """itens: pendências brutas (pagador, destino, valor, mes...); acertos: registros de quitação;
    nomes: {empresa_id: nome}. Devolve {empresa_id: {nome, itens, meses, acertos, saldo, ...}}."""
    saida = {eid: {"empresa_id": eid, "nome": nome, "itens": [], "meses": defaultdict(float), "acertos": [],
                   "total_pendencias": 0.0, "acertos_empresa": 0.0, "acertos_familia": 0.0}
             for eid, nome in nomes.items()}
    for it in itens:
        e = efeito_do_item(it.get("pagador"), it.get("destino"), it.get("valor"))
        if not e or e[0] not in saida:
            continue
        eid, efeito = e
        saida[eid]["itens"].append({**it, "efeito": round(efeito, 2)})
        saida[eid]["meses"][it.get("mes") or ""] += efeito
        saida[eid]["total_pendencias"] += efeito
    for a in acertos:
        s = saida.get(a["empresa_id"])
        if not s:
            continue
        s["acertos"].append(a)
        if a["sentido"] == "empresa_paga":
            s["acertos_empresa"] += _num(a["valor"])
        else:
            s["acertos_familia"] += _num(a["valor"])
    for s in saida.values():
        s["saldo"] = round(s["total_pendencias"] - s["acertos_empresa"] + s["acertos_familia"], 2)
        s["total_pendencias"] = round(s["total_pendencias"], 2)
        s["meses"] = {m: round(v, 2) for m, v in sorted(s["meses"].items(), reverse=True)}
        s["frase"] = frase_saldo(s["nome"], s["saldo"])
        s["itens"].sort(key=lambda i: (str(i.get("data") or ""), i.get("descricao") or ""), reverse=True)
    return saida


def destino_valido(valor, empresas_ids):
    """Texto do formulário -> id da empresa (int) ou None (Família). Id que não é da organização vira Família."""
    if valor in (None, "", "familia"):
        return None
    try:
        v = int(valor)
    except (TypeError, ValueError):
        return None
    return v if v in empresas_ids else None


def ler_destino_regra(valor, empresas_ids):
    """Select da regra de fornecedor: '' = não mexe no destino; 'familia' = Família; id = empresa.
    Devolve (define_destino, destino_empresa_id)."""
    if valor in (None, ""):
        return False, None
    return True, destino_valido(valor, empresas_ids)
