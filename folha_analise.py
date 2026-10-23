# -*- coding: utf-8 -*-
"""Análise do holerite: o que conferir, o que mudou do mês anterior e como o que é descontado em folha
se compara com as dívidas cadastradas. Tudo puro (sem banco), para ser testado com os PDFs reais."""
from collections import defaultdict

from planilha_despesas import somar_meses, norm

TOLERANCIA_FIM = 1  # o cadastro e a folha podem contar a parcela do mês de um jeito diferente: 1 mês de folga


def meses_entre(a, b):
    """b - a em meses ('YYYY-MM')."""
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


def _soma(itens):
    return round(sum(i["valor"] for i in itens), 2)


def verificar(h):
    """Conferências do holerite. ok: True = bateu, False = não bateu, None = só informação."""
    r, d = _soma(h["rendimentos"]), _soma(h["descontos"])
    brl = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    checks = [
        {"ok": abs(r - h["bruto"]) < 0.005, "titulo": "Os rendimentos somam o bruto",
         "detalhe": f"{len(h['rendimentos'])} linhas somam {brl(r)}; o contracheque diz {brl(h['bruto'])}."},
        {"ok": abs(d - h["descontos_total"]) < 0.005, "titulo": "Os descontos somam o total de descontos",
         "detalhe": f"{len(h['descontos'])} linhas somam {brl(d)}; o contracheque diz {brl(h['descontos_total'])}."},
        {"ok": abs(h["bruto"] - h["descontos_total"] - h["liquido"]) < 0.005, "titulo": "Bruto − descontos = líquido",
         "detalhe": f"{brl(h['bruto'])} − {brl(h['descontos_total'])} = {brl(round(h['bruto'] - h['descontos_total'], 2))}; o líquido é {brl(h['liquido'])}."},
    ]
    com_prazo = [i for i in h["rendimentos"] + h["descontos"] if i.get("prazo") is not None]
    if com_prazo:
        checks.append({"ok": None, "titulo": f"{len(com_prazo)} linha(s) com prazo",
                       "detalhe": "Linhas com prazo são parcelas (empréstimos) ou ajustes de meses anteriores. Compare com o mês anterior abaixo."})
    return checks


def descontos_por_classe(h):
    por = defaultdict(float)
    for i in h["descontos"]:
        por[i["classe"]] += i["valor"]
    return {k: round(v, 2) for k, v in por.items()}


def comparar(atual, anterior):
    """O que mudou em relação ao holerite do mês anterior: linhas novas, que sumiram e valores que mudaram."""
    mudancas = []
    for natureza, chave in (("rendimento", "rendimentos"), ("desconto", "descontos")):
        grupos_a, grupos_b = defaultdict(list), defaultdict(list)
        for i in atual[chave]:
            grupos_a[i["descricao"]].append(i)
        for i in anterior[chave]:
            grupos_b[i["descricao"]].append(i)
        for desc in list(grupos_a) + [d for d in grupos_b if d not in grupos_a]:
            a, b = list(grupos_a.get(desc, [])), list(grupos_b.get(desc, []))
            for x in list(a):  # iguais não são mudança
                par = next((y for y in b if abs(y["valor"] - x["valor"]) < 0.005), None)
                if par:
                    a.remove(x); b.remove(par)
            for x, y in zip(list(a), list(b)):  # mesmo nome, valor diferente
                mudancas.append({"tipo": "mudou", "natureza": natureza, "descricao": desc, "valor_atual": x["valor"], "valor_anterior": y["valor"],
                                 "delta": round(x["valor"] - y["valor"], 2)})
                a.remove(x); b.remove(y)
            for x in a:
                mudancas.append({"tipo": "novo", "natureza": natureza, "descricao": desc, "valor_atual": x["valor"], "valor_anterior": None, "delta": x["valor"], "prazo": x.get("prazo")})
            for y in b:
                mudancas.append({"tipo": "sumiu", "natureza": natureza, "descricao": desc, "valor_atual": None, "valor_anterior": y["valor"], "delta": -y["valor"], "prazo": y.get("prazo")})
    return {"liquido_delta": round(atual["liquido"] - anterior["liquido"], 2), "bruto_delta": round(atual["bruto"] - anterior["bruto"], 2),
            "descontos_delta": round(atual["descontos_total"] - anterior["descontos_total"], 2), "mudancas": mudancas,
            "competencia_anterior": anterior["competencia"]}


def analisar_dividas(atual, anterior, fixos):
    """Empréstimos descontados em folha x dívidas cadastradas (gastos fixos). fixos: dicionários de gastos_fixos.

    O prazo da folha é lido como as parcelas que ainda faltam. Como não dá para saber se a parcela do próprio mês entra na conta,
    o fim estimado é uma faixa: de (prazo − 1) a (prazo) meses depois da competência."""
    emprestimos = [i for i in atual["descontos"] if i["classe"] == "emprestimo"]
    disponiveis = [dict(f) for f in fixos if f.get("frequencia", "mensal") == "mensal"]
    anteriores = list(anterior["descontos"]) if anterior else []
    linhas = []
    for e in emprestimos:
        # tendência: o mesmo empréstimo (mesmo valor) no mês anterior, com o prazo diminuindo 1 por mês
        tendencia, anterior_prazo = "desconhecida", None
        if anterior and e["prazo"] is not None:
            par = next((y for y in anteriores if y["classe"] == "emprestimo" and abs(y["valor"] - e["valor"]) < 0.005 and y["prazo"] is not None), None)
            if par:
                anterior_prazo = par["prazo"]
                n = meses_entre(anterior["competencia"], atual["competencia"])
                tendencia = "restantes" if n > 0 and par["prazo"] - e["prazo"] == n else "inconsistente"
                anteriores.remove(par)
        fim_cedo = somar_meses(atual["competencia"], max(e["prazo"] - 1, 0)) if e["prazo"] is not None else None
        fim_tarde = somar_meses(atual["competencia"], e["prazo"]) if e["prazo"] is not None else None
        fixo = next((f for f in disponiveis if abs(float(f["valor"]) - e["valor"]) < 0.005), None)
        linha = {"descricao": e["descricao"], "valor": e["valor"], "prazo": e["prazo"], "prazo_anterior": anterior_prazo, "tendencia": tendencia,
                 "fim_cedo": fim_cedo, "fim_tarde": fim_tarde, "fixo": None, "status": "sem_cadastro", "fim_cadastro": None, "diferenca_meses": None}
        if fixo:
            disponiveis.remove(fixo)
            linha["fixo"] = fixo
            linha["fim_cadastro"] = fixo.get("mes_fim")
            if not fixo.get("mes_fim") or fim_cedo is None:
                linha["status"] = "cadastro_sem_fim"
            else:
                if fim_cedo <= fixo["mes_fim"] <= fim_tarde:
                    dif = 0
                elif fixo["mes_fim"] < fim_cedo:
                    dif = meses_entre(fixo["mes_fim"], fim_cedo)
                else:
                    dif = -meses_entre(fim_tarde, fixo["mes_fim"])
                linha["diferenca_meses"] = dif  # > 0: o cadastro termina ANTES do que a folha indica
                linha["status"] = "ok" if abs(dif) <= TOLERANCIA_FIM else "prazo_diferente"
        linhas.append(linha)
    # marcados como 'descontado em folha' que não aparecem em nenhum desconto do holerite
    valores_folha = [i["valor"] for i in atual["descontos"]]
    so_cadastro = [f for f in fixos if f.get("em_folha") and not any(abs(float(f["valor"]) - v) < 0.005 for v in valores_folha)]
    return {"linhas": linhas, "so_cadastro": so_cadastro,
            "total_folha": round(sum(l["valor"] for l in linhas), 2),
            "total_sem_cadastro": round(sum(l["valor"] for l in linhas if l["status"] == "sem_cadastro"), 2),
            "terminando": [l for l in linhas if l["prazo"] is not None and l["prazo"] <= 1]}


def sugerir_pessoa(servidor_nome, pessoas):
    """Pessoa cujo nome (todas as palavras) aparece no nome do holerite. Só devolve se for UMA só."""
    alvo = set(norm_palavras(servidor_nome))
    achadas = [p for p in pessoas if norm_palavras(p["nome"]) and set(norm_palavras(p["nome"])) <= alvo]
    return achadas[0] if len(achadas) == 1 else None


def norm_palavras(texto):
    import re, unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn").lower()
    return re.findall(r"[a-z0-9]+", t)
