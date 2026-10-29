# -*- coding: utf-8 -*-
"""Transferências entre a Família e a Empresa: acesso ao banco."""
import db
from db import get_conn, query_all, query_one
from transferencias_logica import OPERACOES


def cliente_da_organizacao(organizacao_id):
    row = query_one("SELECT cliente_id FROM organizacoes WHERE id = %s", (organizacao_id,))
    return row["cliente_id"] if row else None


def categoria_padrao(organizacao_id, candidatos, tipo_categoria):
    """A primeira categoria que já existe com um dos nomes (sem diferenciar maiúscula); se nenhuma existe, cria a primeira."""
    for nome in candidatos:
        achada = query_one("SELECT id FROM categorias WHERE organizacao_id = %s AND lower(nome) = lower(%s) AND tipo = %s AND ativa = true",
                           (organizacao_id, nome, tipo_categoria))
        if achada:
            return achada["id"]
    return db.garantir_categoria(organizacao_id, candidatos[0], tipo_categoria)


def forma_padrao(organizacao_id, tipo_lancamento):
    """'Transferência' ou 'Pix' se existirem; senão a primeira forma ativa que serve para o tipo. None se não houver nenhuma."""
    for nome in ("Transferência", "Pix"):
        f = query_one("SELECT id FROM formas_pagamento WHERE organizacao_id = %s AND nome = %s AND ativa = true AND aplica_a IN (%s, 'ambos')", (organizacao_id, nome, tipo_lancamento))
        if f:
            return f["id"]
    f = query_one("SELECT id FROM formas_pagamento WHERE organizacao_id = %s AND ativa = true AND aplica_a IN (%s, 'ambos') ORDER BY id LIMIT 1", (organizacao_id, tipo_lancamento))
    return f["id"] if f else None


def criar_transferencia(cliente_id, chave, data, valor, descricao, origem, destino, criado_por):
    """Cria a transferência e os DOIS lançamentos de uma vez (tudo ou nada).
    origem/destino: {'org': id, 'categoria_id', 'forma_id', 'conta_id', 'nome': nome do espaço, 'fora': bool}. A origem é uma despesa; o destino, uma receita."""
    op = OPERACOES[chave]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO transferencias (cliente_id, operacao, data, valor, descricao, org_origem_id, org_destino_id, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (cliente_id, chave, data, valor, descricao, origem["org"], destino["org"], criado_por))
            tid = cur.fetchone()["id"]
            ids = []
            for lado, tipo, contra in ((origem, "despesa", destino), (destino, "receita", origem)):
                obs = f"{op['nome']}: {'para' if tipo == 'despesa' else 'de'} {contra['nome']}."
                cur.execute(
                    """INSERT INTO lancamentos (organizacao_id, data, tipo, valor, descricao, categoria_id, forma_pagamento_id, conta_bancaria_id,
                              observacao, criado_por, criado_em, transferencia_id, fora_do_resultado)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s) RETURNING id""",
                    (lado["org"], data, tipo, valor, descricao, lado["categoria_id"], lado["forma_id"], lado["conta_id"], obs, criado_por, tid, lado["fora"]))
                ids.append(cur.fetchone()["id"])
            cur.execute("UPDATE transferencias SET lancamento_origem_id = %s, lancamento_destino_id = %s WHERE id = %s", (ids[0], ids[1], tid))
        conn.commit()
        return tid
    except Exception:
        conn.rollback()
        raise


_BASE = """SELECT t.*, oo.nome AS origem_nome, od.nome AS destino_nome, oo.tipo AS origem_tipo
           FROM transferencias t JOIN organizacoes oo ON oo.id = t.org_origem_id JOIN organizacoes od ON od.id = t.org_destino_id"""


def listar_transferencias(cliente_id, org_ids, mes=None):
    """As transferências do cliente que tocam algum dos espaços a que a pessoa tem acesso."""
    sql, p = _BASE + " WHERE t.cliente_id = %(c)s AND (t.org_origem_id = ANY(%(o)s) OR t.org_destino_id = ANY(%(o)s))", {"c": cliente_id, "o": list(org_ids)}
    if mes:
        sql += " AND to_char(t.data, 'YYYY-MM') = %(m)s"; p["m"] = mes
    return query_all(sql + " ORDER BY t.data DESC, t.id DESC", p)


def buscar_transferencia(cliente_id, transferencia_id):
    return query_one(_BASE + " WHERE t.id = %s AND t.cliente_id = %s", (transferencia_id, cliente_id))


def desfazer_transferencia(transferencia_id):
    """Apaga os dois lançamentos e a transferência (tudo ou nada)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT lancamento_origem_id, lancamento_destino_id FROM transferencias WHERE id = %s", (transferencia_id,))
            t = cur.fetchone()
            if not t:
                return False
            cur.execute("DELETE FROM lancamentos WHERE transferencia_id = %s", (transferencia_id,))
            cur.execute("DELETE FROM transferencias WHERE id = %s", (transferencia_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
