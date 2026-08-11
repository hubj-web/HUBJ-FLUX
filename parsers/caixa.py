# -*- coding: utf-8 -*-
"""
Parser para faturas de Cartão CAIXA (Elo/Diners) - portado do módulo local
original de Cartão de Crédito, já testado e validado contra faturas reais.

Estratégia:
- Página 1: texto corrido (via pdfplumber) para extrair os dados de resumo
  da fatura (vencimento, valor total, limite).
- Demais páginas ("Informações Complementares"): usamos coordenadas de
  palavras para reconstruir as tabelas de compras, porque essas páginas
  podem ter DUAS tabelas lado a lado (quando há muitas transações, a CAIXA
  divide em colunas) - uma extração ingênua de texto embaralha as linhas.
"""
import re
import pdfplumber

DATE_RE = re.compile(r"^\d{2}/\d{2}$")
VALUE_RE = re.compile(r"^([\d.]+,\d{2})([DC])$")
INSTALL_RE = re.compile(r"^(.*?)\s+(\d{2})\s+DE\s+(\d{2})\s*$")


def _money_to_float(s):
    if s is None:
        return None
    s = s.strip().replace("R$", "").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_layout_text(pdf_path, page_num=None):
    """Extrai texto preservando o layout espacial, em Python puro."""
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages if page_num is None else [pdf.pages[page_num]]
        return "\n".join(p.extract_text(layout=True) or "" for p in pages)


def _find_after(label, text, pattern=r"R\$\s*[\d.,]+"):
    idx = text.find(label)
    if idx == -1:
        return None
    m = re.search(pattern, text[idx:idx + 400])
    return m.group(0) if m else None


def parse_summary(pdf_path):
    """Extrai os dados de resumo da 1a pagina (texto corrido)."""
    raw_text = _extract_layout_text(pdf_path, page_num=0)
    text = re.sub(r"[ \t]{2,}", " ", raw_text)

    data = {}

    m = re.search(r"(\d{4}\.[X\d]{4}\.[X\d]{4}\.\d{4})", text)
    data["cartao_mascara"] = m.group(1) if m else None
    data["cartao_final"] = data["cartao_mascara"].split(".")[-1] if data["cartao_mascara"] else None

    data["titular"] = None
    lines = [l.strip() for l in text.split("\n")]
    for i, line in enumerate(lines):
        if re.search(r"\d{2}/\d{2}/\d{4}", line):
            for cand in lines[i + 1:i + 4]:
                if cand and re.match(r"^[A-ZÀ-Ü][A-ZÀ-Ü \.]{5,60}$", cand):
                    data["titular"] = cand
                    break
            if data["titular"]:
                break

    venc = _find_after("VENCIMENTO", text, pattern=r"\d{2}/\d{2}/\d{4}")
    data["vencimento"] = venc

    total = _find_after("VALOR TOTAL DESTA FATURA", text)
    data["valor_total"] = _money_to_float(total) if total else None

    m = re.search(r"Limite Total[\s\-]*R\$\s*([\d.,]+)", text)
    data["limite_total"] = _money_to_float(m.group(1)) if m else None

    m = re.search(r"R\$\s*([\d.,]+)\s*que corresponde a", text, re.S)
    data["valor_minimo"] = _money_to_float(m.group(1)) if m else None

    return data, text


def parse_complementary(pdf_path, n_pages):
    info = {}
    full_text = ""
    for p in range(n_pages):
        full_text += _extract_layout_text(pdf_path, page_num=p) + "\n"
    full_text = re.sub(r"[ \t]{2,}", " ", full_text)

    m = re.search(r"Limites.*?TOTAL\s+R\$\s*([\d.,]+)\s*\n?.*?UTILIZADO\s+R\$\s*([\d.,]+)"
                  r"\s*\n?.*?SAQUE INTERNACIONAL\s+R\$\s*([\d.,]+)\s*\n?.*?DISPONIVEL\s+R\$\s*([\d.,]+)",
                  full_text, re.S)
    if m:
        info["limite_total"] = _money_to_float(m.group(1))
        info["limite_utilizado"] = _money_to_float(m.group(2))
        info["limite_saque_internacional"] = _money_to_float(m.group(3))
        info["limite_disponivel"] = _money_to_float(m.group(4))

    m = re.search(r"Melhor data para compra:\s*(\d{2}/\d{2}/\d{4})", full_text)
    info["melhor_data_compra"] = m.group(1) if m else None

    m = re.search(r"Saldo previsto próxima fatura:\s*R\$\s*([\d.,]+)", full_text)
    info["saldo_previsto_proxima_fatura"] = _money_to_float(m.group(1)) if m else None

    m = re.search(r"DESPESAS A VENCER:\s*R\$\s*([\d.,]+)", full_text)
    info["despesas_a_vencer"] = _money_to_float(m.group(1)) if m else None

    return info


def _cluster_lines(words, tol=2.5):
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    current = []
    current_top = None
    for w in words:
        if current_top is None or abs(w["top"] - current_top) <= tol:
            current.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            lines.append(current)
            current = [w]
            current_top = w["top"]
    if current:
        lines.append(current)
    return lines


def _find_all_columns(words):
    """Localiza TODAS as tabelas de uma página (algumas faturas colocam duas
    tabelas lado a lado quando há muitas transações)."""
    by_top = {}
    for w in words:
        by_top.setdefault(round(w["top"], 1), []).append(w)

    anchors = []
    for top, ws in by_top.items():
        texts = {w["text"]: w["x0"] for w in ws}
        if "Data" in texts and "Descrição" in texts and any("Cidade" in t for t in texts):
            cidade_x = next(x for t, x in texts.items() if "Cidade" in t)
            anchors.append((texts["Data"], texts["Descrição"], cidade_x, cidade_x + 40))

    if not anchors:
        return []

    anchors.sort(key=lambda a: a[0])
    groups = [[anchors[0]]]
    for a in anchors[1:]:
        if a[0] - groups[-1][-1][0] <= 15:
            groups[-1].append(a)
        else:
            groups.append([a])

    columns = []
    for g in groups:
        date_x = min(a[0] for a in g)
        desc_x = min(a[1] for a in g)
        city_x = min(a[2] for a in g)
        value_x = min(a[3] for a in g)
        columns.append({"date_x": date_x - 5, "desc_x": desc_x - 5, "city_x": city_x - 5, "value_x": value_x})

    columns.sort(key=lambda c: c["date_x"])
    for i, col in enumerate(columns):
        col["x_max"] = columns[i + 1]["date_x"] if i + 1 < len(columns) else 10_000
    return columns


def _row_from_words(row_words, bounds):
    date_words, desc_words, city_words, value_words = [], [], [], []
    for w in row_words:
        x = w["x0"]
        if x < bounds["desc_x"]:
            date_words.append(w["text"])
        elif x < bounds["city_x"]:
            desc_words.append(w["text"])
        elif x < bounds["value_x"]:
            city_words.append(w["text"])
        else:
            value_words.append(w["text"])

    date = date_words[0] if date_words else None
    desc_full = " ".join(desc_words).strip()
    city = " ".join(city_words).strip()

    parcela_atual, parcela_total = None, None
    m = INSTALL_RE.match(desc_full)
    if m:
        desc_full = m.group(1).strip()
        parcela_atual, parcela_total = int(m.group(2)), int(m.group(3))

    value, sign = None, None
    for tok in value_words:
        vm = VALUE_RE.match(tok)
        if vm:
            value = _money_to_float(vm.group(1))
            sign = vm.group(2)
    if value is None:
        for tok in reversed(city_words):
            vm = VALUE_RE.match(tok)
            if vm:
                value = _money_to_float(vm.group(1))
                sign = vm.group(2)

    return {
        "data": date, "descricao": desc_full, "cidade": city,
        "parcela_atual": parcela_atual, "parcela_total": parcela_total,
        "valor": value, "sinal": sign,
    }


def parse_transactions(pdf_path, tol=2.5):
    transactions = []
    section_re = re.compile(r"^(.*?)\s*\(Cart[aã]o\s*(\d{3,4})\)\s*$")

    current_holder = None
    current_card = None
    current_kind = "GERAL"

    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages):
            all_words = page.extract_words()
            if not all_words:
                continue
            columns = _find_all_columns(all_words)
            if not columns:
                continue

            for bounds in columns:
                words = [w for w in all_words if bounds["date_x"] - 3 <= w["x0"] < bounds["x_max"] - 3]
                lines = _cluster_lines(words, tol=tol)

                for line_words in lines:
                    line_words = sorted(line_words, key=lambda w: w["x0"])
                    line_text = " ".join(w["text"] for w in line_words).strip()

                    if "COMPRAS PARCELADAS" in line_text:
                        current_kind = "COMPRAS PARCELADAS"
                        m2 = section_re.match(line_text)
                        if m2:
                            current_card = m2.group(2)
                        continue
                    if line_text.startswith("COMPRAS") or line_text.startswith("Total COMPRAS"):
                        if "Total" not in line_text:
                            current_kind = "COMPRAS"
                            m2 = section_re.match(line_text)
                            if m2:
                                current_card = m2.group(2)
                        continue
                    if line_text.startswith("OUTROS") or line_text.startswith("Total OUTROS"):
                        if "Total" not in line_text:
                            current_kind = "OUTROS"
                            m2 = section_re.match(line_text)
                            if m2:
                                current_card = m2.group(2)
                        continue
                    if "Total final" in line_text or line_text.startswith("ANUIDADE") or "Demonstrativo" in line_text:
                        continue

                    m = section_re.match(line_text)
                    if m:
                        possible_name = m.group(1).strip()
                        if re.match(r"^[A-ZÀ-Ü][A-ZÀ-Ü \.]{3,}$", possible_name):
                            current_holder = possible_name
                            current_card = m.group(2)
                            current_kind = "GERAL"
                            continue

                    first_word = line_words[0]["text"]
                    if not DATE_RE.match(first_word):
                        continue

                    row = _row_from_words(line_words, bounds)
                    if row["valor"] is None or not row["descricao"]:
                        continue

                    row["titular"] = current_holder or "GERAL"
                    row["cartao"] = current_card
                    row["tipo"] = current_kind
                    row["parcelada"] = current_kind == "COMPRAS PARCELADAS"
                    row["pagina"] = page_index + 1
                    transactions.append(row)

    return transactions, n_pages


def parse_invoice(pdf_path):
    """Função principal: retorna resumo + transações, com reavaliação
    automática (tenta algumas tolerâncias de agrupamento se a primeira
    leitura não bater com o valor total da fatura)."""
    summary, _ = parse_summary(pdf_path)
    valor_total = summary.get("valor_total")

    tentativas = [2.5, 1.5, 3.5, 2.0, 4.0, 5.0]
    melhor = None

    for tol in tentativas:
        transactions, n_pages = parse_transactions(pdf_path, tol=tol)
        soma = sum(t["valor"] for t in transactions if t["sinal"] == "D") - \
            sum(t["valor"] for t in transactions if t["sinal"] == "C")
        diff = abs((valor_total or 0) - soma) if valor_total is not None else None
        if melhor is None or (diff is not None and diff < melhor[0]):
            melhor = (diff if diff is not None else 0, transactions, n_pages, tol)
        if diff is not None and diff < 0.02:
            break

    _, transactions, n_pages, tol_usada = melhor
    complementary = parse_complementary(pdf_path, n_pages)

    result = {}
    result.update(summary)
    result.update(complementary)
    result["transacoes"] = transactions
    result["banco"] = "CAIXA"
    result["_tol_usada"] = tol_usada
    return result


def detect_bank(pdf_path):
    text = _extract_layout_text(pdf_path, page_num=0)
    if "CAIXA" in text.upper() and "cartões" in text.lower():
        return "caixa"
    return "desconhecido"
