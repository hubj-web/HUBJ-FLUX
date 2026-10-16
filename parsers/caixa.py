# -*- coding: utf-8 -*-
"""Parser para faturas de Cartão CAIXA (Elo/Diners)."""
import re
import pdfplumber

DATE_RE = re.compile(r"^\d{2}/\d{2}$")
VALUE_RE = re.compile(r"^([\d.]+,\d{2})([DC])$")
# "05 DE 06", "05 de 06" e também "1 de 10"; e a forma colada "AUTO09D12" (seguro do carro)
INSTALL_RE = re.compile(r"^(.*?)\s+(\d{1,2})\s+DE\s+(\d{1,2})\s*$", re.I)
EMBUTIDA_RE = re.compile(r"^(.*?[A-Za-z])(\d{2})D(\d{2})\s*$")


def _money_to_float(s):
    if s is None:
        return None
    s = s.strip().replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_layout_text(pdf_path, page_num=None):
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

    data["vencimento"] = _find_after("VENCIMENTO", text, pattern=r"\d{2}/\d{2}/\d{4}")
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
    lines, current, current_top = [], [], None
    for w in words:
        if current_top is None or abs(w["top"] - current_top) <= tol:
            current.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            lines.append(current)
            current, current_top = [w], w["top"]
    if current:
        lines.append(current)
    return lines


def _find_all_columns(words):
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
    m = INSTALL_RE.match(desc_full) or EMBUTIDA_RE.match(desc_full)
    if m:
        atual, total = int(m.group(2)), int(m.group(3))
        if total >= 2 and 1 <= atual <= total <= 60:  # "1 de 1" é compra única, não parcelamento
            desc_full = m.group(1).strip()
            parcela_atual, parcela_total = atual, total

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
    current_holder, current_card, current_kind = None, None, "GERAL"

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
                    row["parcelada"] = current_kind == "COMPRAS PARCELADAS" or row["parcela_total"] is not None
                    # linhas de passagem: o saldo da fatura anterior e o pagamento dela. Entram no total da fatura
                    # (se anulam quando o pagamento foi integral), mas NÃO são compras nem créditos de verdade
                    descr_up = row["descricao"].upper()
                    if descr_up.startswith("TOTAL DA FATURA ANTERIOR"):
                        row["tipo"] = "SALDO_ANTERIOR"
                    elif descr_up.startswith("OBRIGADO PELO PAGAMENTO"):
                        row["tipo"] = "PAGAMENTO"
                    row["pagina"] = page_index + 1
                    transactions.append(row)
    return transactions, n_pages


def parse_invoice(pdf_path):
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


# ---------------------------------------------------------------------------
# "Próxima Fatura": print/exportação do app da CAIXA com a fatura ainda aberta (prévia)
# ---------------------------------------------------------------------------
PREVIA_VALOR_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
PREVIA_SECAO_RE = re.compile(r"^([A-ZÀ-Ü][A-ZÀ-Ü ]+?) - \d{6}[X\d]*?(\d{4})$")


def detect_layout(pdf_path):
    """'caixa' (fatura oficial), 'caixa_previa' (Próxima Fatura do app) ou 'desconhecido'."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        texto = pdf.pages[0].extract_text() or ""
    if "Próxima Fatura" in texto and "Total parcial" in texto:
        return "caixa_previa"
    return "caixa" if detect_bank(pdf_path) == "caixa" else "desconhecido"


def parse_previa(pdf_path):
    """Lê a prévia. Crédito e débito vêm em colunas: quem decide é a posição do valor. Parcelas vêm como '06 08'."""
    import pdfplumber
    transacoes, titular, final_secao, cabecalho = [], None, None, ""
    credito_x1 = debito_x0 = None
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            if pi == 0:
                cabecalho = page.extract_text() or ""
            linhas = {}
            for w in page.extract_words():
                linhas.setdefault(round(w["top"] / 3), []).append(w)
            for k in sorted(linhas):
                ws = sorted(linhas[k], key=lambda w: w["x0"])
                txt = " ".join(w["text"] for w in ws)
                if "CRÉDITO" in txt and "DÉBITO" in txt:
                    for w in ws:
                        if w["text"] == "CRÉDITO":
                            credito_x1 = w["x1"]
                        elif w["text"] == "DÉBITO":
                            debito_x0 = w["x0"]
                    continue
                m = PREVIA_SECAO_RE.match(txt)
                if m:
                    titular, final_secao = m.group(1).strip(), m.group(2)
                    continue
                if not (titular and DATE_RE.match(ws[0]["text"]) and PREVIA_VALOR_RE.match(ws[-1]["text"])):
                    continue
                corte = (credito_x1 + debito_x0) / 2 if credito_x1 and debito_x0 else None
                sinal = "C" if corte and ws[-1]["x1"] < corte else "D"
                tokens = [w["text"] for w in ws[1:-1]]
                atual = total = None
                if len(tokens) >= 3 and re.fullmatch(r"\d{2}", tokens[-1]) and re.fullmatch(r"\d{2}", tokens[-2]):
                    a, t = int(tokens[-2]), int(tokens[-1])
                    if t >= 2 and 1 <= a <= t <= 60:
                        atual, total, tokens = a, t, tokens[:-2]
                transacoes.append({
                    "data": ws[0]["text"], "descricao": " ".join(tokens).strip(), "cidade": "",
                    "valor": _money_to_float(ws[-1]["text"]), "sinal": sinal,
                    "parcela_atual": atual, "parcela_total": total, "parcelada": total is not None,
                    "tipo": "COMPRAS PARCELADAS" if total else "COMPRAS", "titular": titular, "cartao": final_secao, "pagina": pi + 1,
                })
    m_total = re.search(r"Total parcial \(R\$\):\s*([\d.]+,\d{2})", cabecalho)
    m_final = re.search(r"\*{4}\s+(\d{4})", cabecalho)
    m_data = re.search(r"Cotação Dólar em (\d{2}/\d{2}/\d{4})", cabecalho)
    return {
        "banco": "caixa", "previa": True, "cartao_final": m_final.group(1) if m_final else None,
        "titular": transacoes[0]["titular"] if transacoes else None,
        "valor_total": _money_to_float(m_total.group(1)) if m_total else None, "valor_minimo": None, "vencimento": None,
        "limite_total": None, "limite_utilizado": None, "limite_disponivel": None,
        "data_referencia": m_data.group(1) if m_data else None, "transacoes": transacoes,
    }
