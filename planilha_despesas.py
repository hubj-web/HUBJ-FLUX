# -*- coding: utf-8 -*-
"""Importador da planilha de despesas (.xlsx): lê as linhas e decide, para cada uma, o que fazer.

Cada linha vira um destes resultados (status):
  criar      -> cadastra como gasto fixo
  pausar     -> cadastra pausado (fora dos números do planejamento), p. ex. o que é pago com créditos
  na_fatura  -> parcela no cartão: NÃO cadastra, a fatura importada e a projeção já cobrem
  sem_valor  -> linha sem valor (mercado, combustível...): fica para o Controle por categoria
  duplicado  -> já existe um gasto igual cadastrado
  ignorado   -> o usuário escolheu não importar esse tipo de pagamento
"""
import io
import logging
import re
import unicodedata
from collections import Counter

ACOES = {
    "normal": "Gasto normal",
    "cartao": "Pago no cartão (já vem da fatura)",
    "creditos": "Pago com créditos (importar pausado)",
    "folha": "Descontado em folha (já sai do salário)",
    "ignorar": "Não importar",
}
_PALAVRAS_CARTAO = {"cc", "cartao", "elo", "visa", "master", "mastercard", "amex", "hipercard"}
_PALAVRAS_CREDITOS = {"vp", "permuta", "escambo"}          # inequívocas
_PALAVRAS_CREDITOS_FRACAS = {"credito", "creditos"}        # só valem se não for cartão ("Cartão de Crédito" é cartão)
_FREQ_POR_MESES = {1: "mensal", 2: "bimestral", 3: "trimestral", 6: "semestral", 12: "anual"}
_PASSO = {"mensal": 1, "bimestral": 2, "trimestral": 3, "semestral": 6, "anual": 12}
LIMITE_BYTES = 5_000_000
log = logging.getLogger(__name__)


class ErroPlanilha(Exception):
    """Problema que o usuário consegue entender e corrigir (mensagem já em português)."""


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower().strip()


def norm(s):
    """Só letras e números, sem acento: 'HUB-J' e 'HUBJ' ficam iguais."""
    return re.sub(r"[^a-z0-9]+", "", _sem_acento(s))


def somar_meses(mes, n):
    ano, m = int(mes[:4]), int(mes[5:7])
    t = ano * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def centavos(v):
    return int(round(float(v) * 100))


def _valor(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2) if v > 0 else None
    t = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        x = round(float(t), 2)
    except ValueError:
        return None
    return x if x > 0 else None


def _dia(v):
    try:
        d = int(float(str(v).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return d if 1 <= d <= 31 else None


def _parcela(txt):
    """Devolve (frequencia, estimado, atual, total, aviso)."""
    t = _sem_acento(txt)
    m = re.fullmatch(r"(\d+)\s*(?:de|/)\s*(\d+)", t)
    if m:
        atual, total = int(m.group(1)), int(m.group(2))
        if atual < 1 or total < atual:
            return "mensal", False, None, None, f"Parcela \"{txt}\" não faz sentido; tratei como mensal."
        return "mensal", False, atual, total, None
    m = re.search(r"(\d+)\s*em\s*\1\s*mes", t) or re.search(r"a cada\s*(\d+)\s*mes", t)
    if m:
        freq = _FREQ_POR_MESES.get(int(m.group(1)))
        if freq:
            return freq, False, None, None, None
    for nome in ("anual", "semestral", "trimestral", "bimestral"):
        if nome in t:
            return nome, False, None, None, None
    if "variavel" in t:
        return "mensal", True, None, None, None
    if t.startswith("mensal"):
        return "mensal", False, None, None, None
    return "mensal", False, None, None, f"Parcela \"{txt}\" não reconhecida; tratei como mensal." if t else "Sem informação de parcela; tratei como mensal."


def acao_padrao(tipo):
    palavras = set(re.findall(r"[a-z0-9]+", _sem_acento(tipo)))
    if palavras & _PALAVRAS_CREDITOS:
        return "creditos"
    if palavras & _PALAVRAS_CARTAO:
        return "cartao"
    if palavras & _PALAVRAS_CREDITOS_FRACAS:
        return "creditos"
    return "normal"


# ---------- leitura ----------

def ler_planilha(conteudo):
    """bytes do .xlsx -> lista de linhas cruas. Lança ErroPlanilha com mensagem clara."""
    if len(conteudo) > LIMITE_BYTES:
        raise ErroPlanilha("O arquivo é grande demais (limite de 5 MB).")
    try:
        import openpyxl
    except ImportError:
        log.exception("openpyxl não está instalado no servidor")
        raise ErroPlanilha("O servidor não tem o componente que lê planilhas do Excel. Avise o suporte.")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        todas = [list(r) for r in ws.iter_rows(values_only=True)]
    except Exception:
        log.exception("falha ao abrir a planilha")  # a causa real fica no log; o usuário vê a mensagem simples
        raise ErroPlanilha("Não consegui abrir o arquivo. Envie uma planilha do Excel (.xlsx).")
    cab_i = next((i for i, r in enumerate(todas[:15]) if any(_sem_acento(c).startswith("descri") for c in r if c)), None)
    if cab_i is None:
        raise ErroPlanilha("Não achei a linha de títulos. A primeira coluna precisa se chamar \"Descrição\".")
    cab = todas[cab_i]
    col = {}
    for j, c in enumerate(cab):
        h = _sem_acento(c)
        if h.startswith("descri"):
            col.setdefault("descricao", j)
        elif h.startswith("fornecedor"):
            col.setdefault("fornecedor", j)
        elif h == "valor":
            col.setdefault("valor", j)
        elif h.startswith("parcela"):
            col.setdefault("parcela", j)
        elif h.startswith("venc") or h == "dia":
            col.setdefault("dia", j)
        elif h in ("tipo", "forma", "forma de pagamento", "pagamento"):
            col.setdefault("tipo", j)
        elif h.startswith("%") or "taxa" in h:
            col.setdefault("taxa", j)
        elif h in ("quem", "para quem", "destino"):
            col.setdefault("quem", j)
    if "quem" not in col:  # coluna sem título depois das demais (como na planilha original)
        sem_titulo = [j for j, c in enumerate(cab) if not str(c or "").strip() and j > max(col.values(), default=-1)]
        if sem_titulo:
            col["quem"] = sem_titulo[0]
    faltam = [n for n in ("descricao", "valor", "parcela") if n not in col]
    if faltam:
        nomes = {"descricao": "Descrição", "valor": "Valor", "parcela": "Parcela"}
        raise ErroPlanilha("Faltam colunas na planilha: " + ", ".join(nomes[n] for n in faltam) + ".")
    pega = lambda r, k: (r[col[k]] if k in col and col[k] < len(r) else None)
    linhas = []
    for i, r in enumerate(todas[cab_i + 1:], start=cab_i + 2):
        desc = str(pega(r, "descricao") or "").strip()
        if not desc:
            continue
        linhas.append({
            "linha": i, "descricao": desc, "fornecedor": str(pega(r, "fornecedor") or "").strip() or None,
            "valor": _valor(pega(r, "valor")), "parcela_txt": str(pega(r, "parcela") or "").strip(),
            "dia": _dia(pega(r, "dia")), "tipo": str(pega(r, "tipo") or "").strip(),
            "taxa": _valor(pega(r, "taxa")), "quem": str(pega(r, "quem") or "").strip(),
        })
    if not linhas:
        raise ErroPlanilha("A planilha não tem nenhuma linha de gasto.")
    if len(linhas) > 500:
        raise ErroPlanilha("A planilha tem linhas demais (limite de 500).")
    return linhas


def tipos_da_planilha(linhas):
    """Tipos de pagamento distintos, na ordem em que aparecem, com quantas linhas e a ação sugerida."""
    cont = Counter(l["tipo"] for l in linhas)
    return [{"chave": t, "rotulo": t or "(em branco)", "qtd": n, "acao": acao_padrao(t)} for t, n in cont.items()]


def destino_da_pessoa(quem, empresas):
    """'HUB-J' -> id da empresa; qualquer outro (Família, Diego, pets...) -> None (Família)."""
    alvo = norm(quem)
    for e in empresas:
        if alvo and norm(e["nome"]) == alvo:
            return e["id"]
    return None


# ---------- decisão ----------

def classificar(linhas, mes_base, mapa_tipos, empresas, existentes, valores_fatura):
    """existentes: {(norm(nome), centavos)} já cadastrados. valores_fatura: lista de valores da fatura do mês
    (ou None se não há fatura importada para esse mês)."""
    disponiveis = Counter(centavos(v) for v in valores_fatura) if valores_fatura is not None else None
    saida, ja_visto = [], set(existentes)
    for l in linhas:
        avisos = []
        acao = mapa_tipos.get(l["tipo"]) or acao_padrao(l["tipo"])
        if acao not in ACOES:
            acao = "normal"
        item = {"linha": l["linha"], "nome": l["descricao"], "fornecedor": l["fornecedor"], "valor": l["valor"], "tipo": l["tipo"],
                "quem": l["quem"], "acao": acao, "avisos": avisos, "na_fatura": None, "fixo": None}
        if l["valor"] is None:
            item["status"] = "sem_valor"; saida.append(item); continue
        if acao == "ignorar":
            item["status"] = "ignorado"; saida.append(item); continue
        freq, estimado, atual, total, aviso = _parcela(l["parcela_txt"])
        if aviso:
            avisos.append(aviso)
        item["quando"] = (f"parcela {atual} de {total}" if total else ("todo mês, valor varia" if estimado else {"mensal": "todo mês"}.get(freq, f"a cada {_PASSO[freq]} meses")))
        if acao == "cartao":
            if disponiveis is not None:
                c = centavos(l["valor"])
                item["na_fatura"] = disponiveis[c] > 0
                if item["na_fatura"]:
                    disponiveis[c] -= 1
                else:
                    avisos.append("Não achei esse valor na fatura do mês.")
            if total:  # parcela no cartão: a fatura e a projeção já contam
                item["status"] = "na_fatura"; saida.append(item); continue
        dia = l["dia"]
        if dia is None:
            avisos.append("Dia do vencimento não informado: usei o dia 1.")
            dia = 1
        mes_fim = somar_meses(mes_base, total - atual) if total else None
        if freq in ("trimestral", "semestral", "anual", "bimestral") and not total:
            avisos.append(f"Confirme o mês em que começa (usei {mes_base}).")
        obs = []
        if total:
            obs.append(f"Parcela {atual} de {total} em {mes_base}.")
        if acao == "folha":
            obs.append("Descontado em folha (já sai do salário).")
        if acao == "creditos":
            obs.append("Pago com créditos" + (f" (taxa de R$ {l['taxa']:.2f}".replace(".", ",") + ")" if l["taxa"] else "") + "; fora dos números até o módulo de permuta.")
        fixo = {"nome": l["descricao"][:150], "fornecedor": (l["fornecedor"] or None) and l["fornecedor"][:150], "valor": l["valor"], "estimado": estimado,
                "dia_mes": dia, "frequencia": freq, "mes_inicio": mes_base, "mes_fim": mes_fim, "no_cartao": acao == "cartao",
                "categoria_id": None, "destino_empresa_id": destino_da_pessoa(l["quem"], empresas), "ativo": acao != "creditos", "em_folha": acao == "folha",
                "observacao": (" ".join(obs) or None) and " ".join(obs)[:300]}
        chave = (norm(fixo["nome"]), centavos(fixo["valor"]))
        if chave in ja_visto:
            item["status"] = "duplicado"
        else:
            ja_visto.add(chave)
            item["status"] = "criar" if fixo["ativo"] else "pausar"
            item["fixo"] = fixo
        saida.append(item)
    return saida


def resumo(itens):
    r = {s: [] for s in ("criar", "pausar", "na_fatura", "sem_valor", "duplicado", "ignorado")}
    for i in itens:
        r[i["status"]].append(i)
    return r


def valor_mensal(itens):
    """Quanto os itens que entram nos números pesam por mês (trimestral dividido por 3, etc.)."""
    return round(sum(i["fixo"]["valor"] / _PASSO[i["fixo"]["frequencia"]] for i in itens if i.get("fixo") and i["fixo"]["ativo"] and not i["fixo"].get("em_folha")), 2)
