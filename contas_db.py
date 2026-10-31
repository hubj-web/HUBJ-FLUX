# -*- coding: utf-8 -*-
"""Contas a pagar e a receber: acesso ao banco (parceiros = clientes e fornecedores, e títulos)."""
import db
from db import execute, get_conn, query_all, query_one

_BASE = """SELECT t.*, p.nome AS parceiro_nome, c.nome AS categoria_nome, fp.nome AS forma_nome
           FROM titulos t LEFT JOIN parceiros p ON p.id = t.parceiro_id LEFT JOIN categorias c ON c.id = t.categoria_id
           LEFT JOIN formas_pagamento fp ON fp.id = t.forma_pagamento_id"""


# ---------- clientes e fornecedores ----------

def listar_parceiros(organizacao_id, tipo=None, apenas_ativos=True):
    """tipo='cliente' traz clientes e 'ambos'; tipo='fornecedor' traz fornecedores e 'ambos'."""
    sql, params = "SELECT * FROM parceiros WHERE organizacao_id = %s", [organizacao_id]
    if apenas_ativos:
        sql += " AND ativo = true"
    if tipo in ("cliente", "fornecedor"):
        sql += " AND tipo IN (%s, 'ambos')"
        params.append(tipo)
    return query_all(sql + " ORDER BY lower(nome)", params)


def buscar_parceiro(organizacao_id, parceiro_id):
    return query_one("SELECT * FROM parceiros WHERE id = %s AND organizacao_id = %s", (parceiro_id, organizacao_id))


def parceiro_por_nome(organizacao_id, nome):
    return query_one("SELECT * FROM parceiros WHERE organizacao_id = %s AND lower(nome) = lower(%s)", (organizacao_id, nome.strip()))


def criar_parceiro(organizacao_id, nome, tipo, documento=None, email=None, telefone=None, observacao=None):
    return execute(
        """INSERT INTO parceiros (organizacao_id, nome, tipo, documento, email, telefone, observacao)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (organizacao_id, nome.strip(), tipo, documento, email, telefone, observacao),
    )


def atualizar_parceiro(organizacao_id, parceiro_id, nome, tipo, documento, email, telefone, observacao):
    execute(
        """UPDATE parceiros SET nome = %s, tipo = %s, documento = %s, email = %s, telefone = %s, observacao = %s
           WHERE id = %s AND organizacao_id = %s""",
        (nome.strip(), tipo, documento, email, telefone, observacao, parceiro_id, organizacao_id),
    )


def definir_parceiro_ativo(organizacao_id, parceiro_id, ativo):
    execute("UPDATE parceiros SET ativo = %s WHERE id = %s AND organizacao_id = %s", (bool(ativo), parceiro_id, organizacao_id))


def ampliar_tipo_parceiro(organizacao_id, parceiro_id, tipo_necessario):
    """Quem era só fornecedor e passou a ter contas a receber (ou o contrário) vira 'ambos'."""
    execute("UPDATE parceiros SET tipo = 'ambos' WHERE id = %s AND organizacao_id = %s AND tipo <> %s AND tipo <> 'ambos'",
            (parceiro_id, organizacao_id, tipo_necessario))


# ---------- contas ----------

def criar_titulos(organizacao_id, lista, criado_por):
    """Grava todas as parcelas de uma vez (tudo ou nada). Devolve as contas criadas."""
    conn = get_conn()
    criados = []
    try:
        with conn.cursor() as cur:
            for t in lista:
                cur.execute(
                    """INSERT INTO titulos (organizacao_id, tipo, descricao, parceiro_id, categoria_id, valor, vencimento,
                              numero_documento, observacao, parcela_atual, parcela_total, criado_por)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                    (organizacao_id, t["tipo"], t["descricao"], t.get("parceiro_id"), t.get("categoria_id"), t["valor"], t["vencimento"],
                     t.get("numero_documento"), t.get("observacao"), t.get("parcela_atual"), t.get("parcela_total"), criado_por))
                criados.append(cur.fetchone())
        conn.commit()
        return criados
    except Exception:
        conn.rollback()
        raise


def buscar_titulo(organizacao_id, titulo_id):
    return query_one(_BASE + " WHERE t.id = %s AND t.organizacao_id = %s", (titulo_id, organizacao_id))


def listar_titulos(organizacao_id, tipo, situacao, hoje, de=None, ate=None, q=None, parceiro_id=None):
    sql, p = _BASE + " WHERE t.organizacao_id = %(org)s AND t.tipo = %(tipo)s", {"org": organizacao_id, "tipo": tipo, "hoje": hoje}
    if situacao == "abertos":
        sql += " AND t.status = 'aberto'"
    elif situacao == "vencidos":
        sql += " AND t.status = 'aberto' AND t.vencimento < %(hoje)s"
    elif situacao == "pagos":
        sql += " AND t.status = 'pago'"
    elif situacao == "cancelados":
        sql += " AND t.status = 'cancelado'"
    if de:
        sql += " AND t.vencimento >= %(de)s"; p["de"] = de
    if ate:
        sql += " AND t.vencimento <= %(ate)s"; p["ate"] = ate
    if parceiro_id:
        sql += " AND t.parceiro_id = %(parceiro)s"; p["parceiro"] = parceiro_id
    if q:
        sql += " AND (t.descricao ILIKE %(q)s OR p.nome ILIKE %(q)s OR t.numero_documento ILIKE %(q)s)"; p["q"] = f"%{q}%"
    ordem = "t.data_pagamento DESC, t.id DESC" if situacao == "pagos" else "t.vencimento, t.id"
    return query_all(sql + " ORDER BY " + ordem, p)


def atualizar_titulo(organizacao_id, titulo_id, d):
    execute("DELETE FROM titulos_avisos WHERE titulo_id IN (SELECT id FROM titulos WHERE id = %s AND organizacao_id = %s)", (titulo_id, organizacao_id))
    execute(
        """UPDATE titulos SET descricao = %(descricao)s, parceiro_id = %(parceiro_id)s, categoria_id = %(categoria_id)s, valor = %(valor)s,
                  vencimento = %(vencimento)s, numero_documento = %(numero_documento)s, observacao = %(observacao)s
           WHERE id = %(id)s AND organizacao_id = %(org)s AND status = 'aberto'""",
        {**d, "id": titulo_id, "org": organizacao_id},
    )


def marcar_pago(organizacao_id, titulo_id, data_pagamento, valor_pago, forma_id, lancamento_id):
    """Só marca se ainda estiver em aberto (duas pessoas baixando ao mesmo tempo não pagam duas vezes). Devolve se marcou."""
    row = execute(
        """UPDATE titulos SET status = 'pago', data_pagamento = %s, valor_pago = %s, forma_pagamento_id = %s, lancamento_id = %s
           WHERE id = %s AND organizacao_id = %s AND status = 'aberto' RETURNING id""",
        (data_pagamento, valor_pago, forma_id, lancamento_id, titulo_id, organizacao_id),
    )
    return row is not None


def reabrir_titulo(organizacao_id, titulo_id):
    execute("DELETE FROM titulos_avisos WHERE titulo_id IN (SELECT id FROM titulos WHERE id = %s AND organizacao_id = %s)", (titulo_id, organizacao_id))
    execute(
        """UPDATE titulos SET status = 'aberto', data_pagamento = NULL, valor_pago = NULL, forma_pagamento_id = NULL, lancamento_id = NULL
           WHERE id = %s AND organizacao_id = %s""",
        (titulo_id, organizacao_id),
    )


def cancelar_titulo(organizacao_id, titulo_id):
    execute("UPDATE titulos SET status = 'cancelado' WHERE id = %s AND organizacao_id = %s AND status = 'aberto'", (titulo_id, organizacao_id))


def excluir_titulo(organizacao_id, titulo_id):
    execute("DELETE FROM titulos WHERE id = %s AND organizacao_id = %s AND status <> 'pago'", (titulo_id, organizacao_id))


def resumo_titulos(organizacao_id, hoje, dias=7):
    """Os números do painel: quanto está em aberto, o que já venceu e o que vence nos próximos dias, para pagar e para receber."""
    linhas = query_all(
        """SELECT tipo,
                  COALESCE(SUM(valor), 0) AS aberto, COUNT(*) AS n_aberto,
                  COALESCE(SUM(valor) FILTER (WHERE vencimento < %(h)s), 0) AS vencido, COUNT(*) FILTER (WHERE vencimento < %(h)s) AS n_vencido,
                  COALESCE(SUM(valor) FILTER (WHERE vencimento >= %(h)s AND vencimento <= %(h)s + %(d)s), 0) AS proximos,
                  COUNT(*) FILTER (WHERE vencimento >= %(h)s AND vencimento <= %(h)s + %(d)s) AS n_proximos
           FROM titulos WHERE organizacao_id = %(o)s AND status = 'aberto' GROUP BY tipo""",
        {"o": organizacao_id, "h": hoje, "d": dias},
    )
    vazio = {"aberto": 0.0, "n_aberto": 0, "vencido": 0.0, "n_vencido": 0, "proximos": 0.0, "n_proximos": 0}
    por_tipo = {l["tipo"]: {k: (float(v) if k in ("aberto", "vencido", "proximos") else int(v)) for k, v in l.items() if k != "tipo"} for l in linhas}
    return {"pagar": por_tipo.get("pagar", dict(vazio)), "receber": por_tipo.get("receber", dict(vazio)), "dias": dias}
