# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras
from flask import g
from config import Config


def get_conn():
    """Uma conexão por requisição, guardada em flask.g e fechada ao final."""
    if "db_conn" not in g:
        g.db_conn = psycopg2.connect(Config.DATABASE_URL, sslmode="require")
    return g.db_conn


def close_conn(exception=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def query_one(sql, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def query_all(sql, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        conn.commit()
        if cur.description:
            return cur.fetchone()
        return None


# ---------- Usuários / Organizações (o que a autenticação precisa) ----------

def buscar_usuario_por_email(email):
    return query_one("SELECT * FROM usuarios WHERE email = %s", (email.strip().lower(),))


def criar_super_admin(email):
    return execute(
        """INSERT INTO usuarios (email, papel, status, criado_em)
           VALUES (%s, 'super_admin', 'ativo', now())
           RETURNING *""",
        (email.strip().lower(),),
    )


def atualizar_login(usuario_id, google_sub, nome):
    execute(
        """UPDATE usuarios SET google_sub = %s, nome = COALESCE(nome, %s),
                                ultimo_login_em = now()
           WHERE id = %s""",
        (google_sub, nome, usuario_id),
    )


def buscar_organizacao(organizacao_id):
    if organizacao_id is None:
        return None
    return query_one("SELECT * FROM organizacoes WHERE id = %s", (organizacao_id,))


def contar_usuarios_ativos(organizacao_id):
    row = query_one(
        "SELECT COUNT(*) AS n FROM usuarios WHERE organizacao_id = %s AND status != 'bloqueado'",
        (organizacao_id,),
    )
    return row["n"] if row else 0
