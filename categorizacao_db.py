# -*- coding: utf-8 -*-
"""Categorização em massa das compras do cartão: consultas ao banco."""
import db
from db import query_one, query_all

_ALVO = "COALESCE(lc.tipo, '') NOT IN ('SALDO_ANTERIOR', 'PAGAMENTO')"


def cobertura(organizacao_id):
    """Quanto do gasto no cartão (só débitos, sem pagamento de fatura nem saldo anterior) ainda está sem categoria."""
    r = query_one(
        "SELECT COALESCE(SUM(lc.valor) FILTER (WHERE lc.categoria_id IS NULL), 0) AS sem, COALESCE(SUM(lc.valor), 0) AS total, "
        "COUNT(*) FILTER (WHERE lc.categoria_id IS NULL) AS n_sem, COUNT(*) AS n "
        "FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id "
        f"WHERE c.organizacao_id = %s AND lc.sinal = 'D' AND {_ALVO}", (organizacao_id,))
    sem, total = float(r["sem"]), float(r["total"])
    return {"sem": round(sem, 2), "total": round(total, 2), "n_sem": int(r["n_sem"]), "n": int(r["n"]), "pct_sem": round(sem / total * 100, 1) if total else 0.0}


def aplicar_por_chave(organizacao_id, chave, categoria_id):
    """Põe a categoria em TODAS as compras sem categoria desse fornecedor (a mesma chave da lista). Quem já tem categoria não é tocado.
    Devolve (quantas compras, quanto em R$ de débito)."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE lancamentos_cartao lc SET categoria_id = %s FROM faturas f JOIN cartoes c ON c.id = f.cartao_id "
                "WHERE lc.fatura_id = f.id AND c.organizacao_id = %s AND lc.categoria_id IS NULL AND " + _ALVO + " AND " + db._FORN_SQL + " = %s "
                "RETURNING lc.valor, lc.sinal", (categoria_id, organizacao_id, chave))
            rows = cur.fetchall()
        conn.commit()   # gravação de verdade: uma função de leitura não confirma, e a última do lote se perdia
    except Exception:
        conn.rollback()
        raise
    return len(rows), round(sum(float(r["valor"]) for r in rows if r["sinal"] == "D"), 2)
