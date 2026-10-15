# -*- coding: utf-8 -*-
"""Atalhos que podem aparecer na barra de baixo. Início, o botão + e Mais
são sempre fixos (Mais garante que ninguém fique sem acesso às telas)."""

# chave: (ícone, rótulo, endpoint, prefixos de URL para marcar como ativo)
CATALOGO = {
    "extrato": ("🧾", "Extrato", "lanc.extrato", ["/extrato"]),
    "cartao": ("💳", "Cartão", "cartao.painel", ["/cartao"]),
    "planejamento": ("📝", "Planejamento", "plan.index", ["/planejamento"]),
    "controle": ("🎛️", "Controle", "controle.index", ["/controle"]),
    "metas": ("🎯", "Metas", "metas.index", ["/metas"]),
    "relatorios": ("📊", "Relatórios", "relatorios.index", ["/relatorios"]),
    "recorrentes": ("🔁", "Recorrentes", "lanc.recorrentes", ["/lancamentos/recorrentes"]),
    "alertas": ("🔔", "Alertas", "alertas.index", ["/alertas", "/lembretes"]),
    "mensal": ("🧮", "Mensal", "mensal.index", ["/mensal"]),
}
PADRAO = ["extrato", "cartao"]
MAXIMO = 2


def limpar(valores):
    """Aceita lista ou texto 'a,b' e devolve só chaves válidas, sem repetir, até o máximo."""
    if valores is None:
        return []
    if isinstance(valores, str):
        valores = valores.split(",")
    saida = []
    for v in valores:
        v = (v or "").strip()
        if v in CATALOGO and v not in saida:
            saida.append(v)
    return saida[:MAXIMO]


def resolver_chaves(usuario, prefs):
    """Escolha do usuário > padrão da organização > padrão do sistema."""
    for fonte in ((usuario or {}).get("nav_atalhos"), (prefs or {}).get("nav_atalhos_padrao")):
        chaves = limpar(fonte)
        if chaves:
            return chaves
    return list(PADRAO)
