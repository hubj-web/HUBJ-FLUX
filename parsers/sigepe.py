# -*- coding: utf-8 -*-
"""Leitor do contracheque do Sigepe (servidores federais): 'COMPROVANTE DE RENDIMENTOS - FOLHA ...'.

Lê só o texto do PDF e devolve valores. CPF, matrícula e dados de conta NÃO são lidos nem guardados."""
import re
import unicodedata
from datetime import date

import pdfplumber

MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}
_DINHEIRO = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")


class ErroHolerite(Exception):
    """Mensagem em português que o usuário entende e consegue agir."""


def _num(texto):
    return round(float(texto.replace(".", "").replace(",", ".")), 2)


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def classe_do_item(natureza, descricao):
    d = _sem_acento(descricao)
    if natureza == "desconto":
        if d.startswith("EMPREST") or "CONSIGN" in d or "FINANCIAM" in d:
            return "emprestimo"
        if "SEGURIDADE" in d or "PREVID" in d or "INSS" in d or d.startswith("CONT. PLANO"):
            return "previdencia"
        if "IMPOSTO DE RENDA" in d or "IRRF" in d:
            return "imposto"
        if "SAUDE" in d or "PRE-ESCOLAR" in d or "COPART" in d or "PLANO" in d:
            return "beneficio"
        return "outros"
    if d.startswith("VENCIMENTO") or d.startswith("IQ") or "GRATIFIC" in d or "ADICIONAL" in d or "SALARIO" in d:
        return "remuneracao"
    if "AUXILIO" in d or "ASSISTENCIA" in d or "PER CAPITA" in d:
        return "beneficio"
    return "outros"


def _linhas(palavras, tolerancia=3.5):
    """Agrupa palavras na mesma linha visual (o valor fica ~1 ponto acima da descrição)."""
    grupos, atual, base = [], [], None
    for w in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
        if base is None or w["top"] - base > tolerancia:
            if atual:
                grupos.append(atual)
            atual, base = [w], w["top"]
        else:
            atual.append(w)
    if atual:
        grupos.append(atual)
    return [sorted(g, key=lambda w: w["x0"]) for g in grupos]


def ler_contracheque(arquivo):
    """arquivo: caminho ou objeto de arquivo (bytes). Devolve um dicionário com cabeçalho, itens e totais."""
    try:
        pdf = pdfplumber.open(arquivo)
    except Exception:
        raise ErroHolerite("Não consegui abrir o arquivo. Envie o contracheque em PDF.")
    with pdf:
        if not pdf.pages:
            raise ErroHolerite("O PDF está vazio.")
        textos = [(p.extract_text() or "") for p in pdf.pages]
        todo = "\n".join(textos)
        if "COMPROVANTE DE RENDIMENTOS" not in todo.upper() or "SIAPE" not in todo.upper():
            raise ErroHolerite("Este PDF não parece um contracheque do Sigepe (servidor federal). Por enquanto só esse formato é lido: "
                               "você pode lançar o salário à mão, pelo +.")
        p0 = pdf.pages[0]
        pal0 = p0.extract_words()

        def abaixo(rotulo_palavras, x_min, x_max, dy=(4, 16)):
            """Palavras na linha logo abaixo de um rótulo (ex.: o nome embaixo de 'NOME DO SERVIDOR')."""
            ancora = next((w for w in pal0 if w["text"] == rotulo_palavras[0]), None)
            if ancora is None:
                return []
            return [w["text"] for w in sorted(pal0, key=lambda w: w["x0"])
                    if ancora["top"] + dy[0] < w["top"] < ancora["top"] + dy[1] and x_min <= w["x0"] < x_max]

        titulo = next((w for w in pal0 if w["text"] == "COMPROVANTE"), None)
        tipo_folha = fonte = None
        if titulo:
            linha = [w["text"] for w in sorted(pal0, key=lambda w: w["x0"]) if abs(w["top"] - titulo["top"]) < 3]
            tipo_folha = " ".join(linha[linha.index("-") + 1:]) if "-" in linha else None
            fonte = " ".join(w["text"] for w in sorted(pal0, key=lambda w: w["x0"])
                             if titulo["top"] + 8 < w["top"] < titulo["top"] + 25 and w["x0"] > 100) or None
        nome = " ".join(abaixo(["NOME"], 30, 290))
        comp = abaixo(["MÊS/ANO"], 420, 600)
        if len(comp) < 2 or comp[0].upper() not in MESES or not comp[1].isdigit():
            raise ErroHolerite("Não achei o mês/ano de pagamento neste contracheque.")
        competencia = f"{int(comp[1]):04d}-{MESES[comp[0].upper()]:02d}"

        itens, secao = {"rendimento": [], "desconto": []}, None
        totais = None
        for pagina in pdf.pages:
            pal = pagina.extract_words()
            cab = next((w for w in pal if w["text"] == "TIPO"), None)
            fim = next((w for w in pal if w["text"].startswith("Eduque")), None)
            if cab and fim:
                regiao = [w for w in pal if cab["top"] + 5 < w["top"] < fim["top"] - 2]
                for linha in _linhas(regiao):
                    marca = [w["text"] for w in linha if w["x0"] < 90 and w["text"] in ("RENDIMENTOS", "DESCONTOS")]
                    if marca:
                        secao = "rendimento" if marca[0] == "RENDIMENTOS" else "desconto"
                    desc = " ".join(w["text"] for w in linha if 90 <= w["x0"] < 350)
                    prazo = next((int(w["text"]) for w in linha if 350 <= w["x0"] < 450 and re.fullmatch(r"\d{1,3}", w["text"])), None)
                    valor = next((_num(w["text"]) for w in linha if w["x0"] >= 500 and _DINHEIRO.match(w["text"])), None)
                    if valor is None or not desc:
                        continue
                    if secao is None:
                        raise ErroHolerite("Não consegui separar rendimentos e descontos neste contracheque.")
                    itens[secao].append({"descricao": desc, "prazo": prazo, "valor": valor, "classe": classe_do_item(secao, desc)})
            rot = next((w for w in pal if w["text"] == "BRUTO"), None)
            if rot:
                nums = [w for w in pal if rot["top"] + 4 < w["top"] < rot["top"] + 18 and _DINHEIRO.match(w["text"])]
                if len(nums) == 6:
                    base_teto, base_ir, fgts, bruto, desconto, liquido = (_num(w["text"]) for w in sorted(nums, key=lambda w: w["x0"]))
                    totais = {"base_ir": base_ir, "bruto": bruto, "descontos_total": desconto, "liquido": liquido}
        if not itens["rendimento"] and not itens["desconto"]:
            raise ErroHolerite("Não consegui ler a tabela de rendimentos e descontos deste contracheque.")
        if totais is None:
            raise ErroHolerite("Não achei os totais (bruto, desconto e líquido) no rodapé do contracheque.")

        autenticacao = re.search(r"Autentica\S+\s+N\S+\s+([0-9A-F.]+)", todo)
        emissao = re.search(r"Data de emiss\S+:\s*(\d{2})/(\d{2})/(\d{4})", todo)
        return {"tipo_folha": tipo_folha, "fonte": fonte, "servidor_nome": nome, "competencia": competencia,
                "emitido_em": date(int(emissao.group(3)), int(emissao.group(2)), int(emissao.group(1))) if emissao else None,
                "autenticacao": autenticacao.group(1) if autenticacao else None,
                "rendimentos": itens["rendimento"], "descontos": itens["desconto"], **totais}
