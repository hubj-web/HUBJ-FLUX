# -*- coding: utf-8 -*-
"""Módulos que o Super Admin liga ou desliga em cada espaço (Família ou Empresa).

Um módulo só existe para os tipos de espaço listados em 'tipos'. O 'padrao' vale quando o Super Admin ainda não mexeu:
o que a família sempre teve continua ligado; o que é novo vem desligado, para você liberar cliente por cliente."""
from functools import wraps

from flask import abort, g

import db

CATALOGO = {
    "contas_pagar_receber": {
        "nome": "Contas a pagar e a receber",
        "descricao": "Contas com vencimento e situação (em aberto, vencida, paga), clientes e fornecedores, e a baixa que lança no extrato.",
        "tipos": ("empresa",), "padrao": False,
    },
    "holerite": {
        "nome": "Holerite e folha de pagamento",
        "descricao": "Importa o contracheque como entrada, confere os números e compara os descontos em folha com as dívidas.",
        "tipos": ("familia",), "padrao": True,
    },
}
MSG_BLOQUEADO = "Este recurso não está liberado para o seu espaço. Fale com quem administra o sistema para ativar o módulo."


def catalogo_para(tipo):
    return {chave: m for chave, m in CATALOGO.items() if tipo in m["tipos"]}


def padroes(tipo):
    return {chave: m["padrao"] for chave, m in catalogo_para(tipo).items()}


def mapa_modulos(organizacao_id, tipo):
    """{módulo: ligado?} só dos módulos que existem para este tipo de espaço."""
    linhas = {r["modulo"]: r["ativo"] for r in db.query_all(
        "SELECT modulo, ativo FROM espaco_modulos WHERE organizacao_id = %s", (organizacao_id,))}
    return {chave: bool(linhas.get(chave, m["padrao"])) for chave, m in catalogo_para(tipo).items()}


def modulo_ativo(organizacao_id, chave, tipo=None):
    if chave not in CATALOGO:
        return False
    if tipo is None:
        org = db.query_one("SELECT tipo FROM organizacoes WHERE id = %s", (organizacao_id,))
        tipo = org["tipo"] if org else None
    return mapa_modulos(organizacao_id, tipo).get(chave, False)


def definir_modulo(organizacao_id, chave, ativo):
    db.execute(
        """INSERT INTO espaco_modulos (organizacao_id, modulo, ativo) VALUES (%s, %s, %s)
           ON CONFLICT (organizacao_id, modulo) DO UPDATE SET ativo = EXCLUDED.ativo""",
        (organizacao_id, chave, bool(ativo)),
    )


def requer_modulo(chave):
    """Barra a tela (403) se o módulo não estiver ligado no espaço em que a pessoa está. Vai DEPOIS de login_required e requer_organizacao."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not modulo_ativo(g.usuario_atual["organizacao_id"], chave):
                abort(403, description=MSG_BLOQUEADO)
            return f(*args, **kwargs)
        return wrapper
    return deco
