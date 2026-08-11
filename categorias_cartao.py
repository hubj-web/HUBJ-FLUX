# -*- coding: utf-8 -*-
"""Sugestão automática de categoria por palavra-chave na descrição de
compras de cartão - ponto de partida, o usuário pode corrigir depois.
Os nomes aqui devem bater com as categorias padrão criadas em
db.seed_organizacao (CATEGORIAS_PADRAO)."""

REGRAS = [
    ("Transporte", ["UBER", "99APP", "TAXI", "METRO", "BILHETE", "LOCALIZA", "MOVIDA", "POSTO"]),
    ("Alimentação", ["IFOOD", "IFD ", "RESTAURANTE", "LANCHONETE", "CHEF", "CAFE", "PADARIA",
                      "PIZZARIA", "BURGER", "AÇAI", "ACAI"]),
    ("Mercado", ["SUPERMERCADO", " SUP ", "MERCADO", "HORTIFRUTI", "ATACAD"]),
    ("Assinaturas", ["NETFLIX", "SPOTIFY", "YOUTUBE", "PRIME VIDEO", "DISNEY",
                      "HBO", "GOOGLE", "APPLE.COM", "ICLOUD"]),
    ("Saúde", ["DROGARIA", "DROGASIL", "FARMA", "PANVEL", "ODONTO", "CLINICA"]),
    ("Vestuário", ["CALCADOS", "CALÇADOS", "MODA", "CONFECC", "OTICA", "ÓTICA"]),
    ("Educação", ["FACULDADE", "UNIVERSIDADE", "ESCOLA", "CURSO"]),
]


def sugerir_categoria(descricao):
    if not descricao:
        return None
    desc = f" {descricao.upper()} "
    for nome_categoria, palavras in REGRAS:
        for p in palavras:
            if p in desc:
                return nome_categoria
    return None
