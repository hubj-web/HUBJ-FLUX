# -*- coding: utf-8 -*-
import psycopg
from psycopg.rows import dict_row
from flask import g
from config import Config


def get_conn():
    """Uma conexão por requisição, guardada em flask.g e fechada ao final."""
    if "db_conn" not in g:
        g.db_conn = psycopg.connect(Config.DATABASE_URL, sslmode="require", row_factory=dict_row)
    return g.db_conn


def close_conn(exception=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def query_one(sql, params=None):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def query_all(sql, params=None):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql, params=None):
    conn = get_conn()
    with conn.cursor() as cur:
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


def listar_usuarios_por_organizacao(organizacao_id):
    return query_all(
        """SELECT id, email, nome, papel, status, criado_em
           FROM usuarios WHERE organizacao_id = %s ORDER BY criado_em""",
        (organizacao_id,),
    )


# ---------- Categorias / Formas de pagamento / Cartões / Pessoas ----------

CATEGORIAS_PADRAO = [
    "Moradia", "Alimentação", "Mercado", "Transporte", "Saúde",
    "Educação", "Lazer", "Assinaturas", "Vestuário", "Outros",
]
FORMAS_PAGAMENTO_PADRAO = ["Dinheiro", "Débito", "Pix", "Boleto", "Cartão de Crédito"]


def seed_organizacao(organizacao_id):
    """Cria categorias e formas de pagamento padrão para uma organização
    recém-criada, para o formulário de lançamento não nascer vazio."""
    for i, nome in enumerate(CATEGORIAS_PADRAO):
        execute(
            "INSERT INTO categorias (organizacao_id, nome, ordem) VALUES (%s, %s, %s) "
            "ON CONFLICT (organizacao_id, nome) DO NOTHING",
            (organizacao_id, nome, i),
        )
    for nome in FORMAS_PAGAMENTO_PADRAO:
        execute(
            "INSERT INTO formas_pagamento (organizacao_id, nome, padrao) VALUES (%s, %s, true)",
            (organizacao_id, nome),
        )


def listar_categorias(organizacao_id, apenas_ativas=True):
    sql = "SELECT * FROM categorias WHERE organizacao_id = %s"
    if apenas_ativas:
        sql += " AND ativa = true"
    sql += " ORDER BY ordem, nome"
    return query_all(sql, (organizacao_id,))


def listar_subcategorias(categoria_id):
    return query_all(
        "SELECT * FROM subcategorias WHERE categoria_id = %s AND ativa = true ORDER BY nome",
        (categoria_id,),
    )


def listar_formas_pagamento(organizacao_id):
    return query_all(
        "SELECT * FROM formas_pagamento WHERE organizacao_id = %s AND ativa = true ORDER BY nome",
        (organizacao_id,),
    )


def listar_cartoes(organizacao_id):
    return query_all(
        "SELECT * FROM cartoes WHERE organizacao_id = %s AND ativo = true ORDER BY nome",
        (organizacao_id,),
    )


def listar_pessoas(organizacao_id):
    return query_all(
        "SELECT * FROM pessoas WHERE organizacao_id = %s ORDER BY nome",
        (organizacao_id,),
    )


def sugerir_categoria_por_descricao(organizacao_id, descricao):
    """Sugestão automática: procura a descrição nas palavras-chave de cada
    categoria. Só preenche sozinho se EXATAMENTE UMA categoria bater - se
    mais de uma bater, não arrisca escolher errado (fica em branco pra
    seleção manual). Regra vinda da especificação técnica, seção 5.3."""
    if not descricao:
        return None
    categorias = listar_categorias(organizacao_id)
    desc = descricao.lower()
    encontradas = []
    for cat in categorias:
        if not cat["palavras_chave"]:
            continue
        palavras = [p.strip().lower() for p in cat["palavras_chave"].split(",") if p.strip()]
        if any(p in desc for p in palavras):
            encontradas.append(cat["id"])
    return encontradas[0] if len(encontradas) == 1 else None


# ---------- Lançamentos ----------

def criar_lancamento(organizacao_id, dados, criado_por):
    return execute(
        """INSERT INTO lancamentos
             (organizacao_id, data, tipo, valor, descricao, categoria_id, subcategoria_id,
              forma_pagamento_id, cartao_id, pessoa_id, grupo_parcelamento_id,
              parcela_atual, parcela_total, observacao, criado_por, criado_em)
           VALUES (%(organizacao_id)s, %(data)s, %(tipo)s, %(valor)s, %(descricao)s,
                   %(categoria_id)s, %(subcategoria_id)s, %(forma_pagamento_id)s,
                   %(cartao_id)s, %(pessoa_id)s, %(grupo_parcelamento_id)s,
                   %(parcela_atual)s, %(parcela_total)s, %(observacao)s, %(criado_por)s, now())
           RETURNING *""",
        {**dados, "organizacao_id": organizacao_id, "criado_por": criado_por},
    )


def buscar_lancamento(lancamento_id, organizacao_id):
    """Sempre filtrado por organizacao_id - garante que uma organização
    nunca acesse o lançamento de outra, mesmo sabendo o id."""
    return query_one(
        "SELECT * FROM lancamentos WHERE id = %s AND organizacao_id = %s",
        (lancamento_id, organizacao_id),
    )


def atualizar_lancamento(lancamento_id, organizacao_id, dados):
    campos = ["data", "tipo", "valor", "descricao", "categoria_id", "subcategoria_id",
              "forma_pagamento_id", "cartao_id", "pessoa_id", "observacao"]
    sets = ", ".join(f"{c} = %({c})s" for c in campos if c in dados)
    if not sets:
        return
    dados = {**dados, "id": lancamento_id, "organizacao_id": organizacao_id}
    execute(
        f"UPDATE lancamentos SET {sets} WHERE id = %(id)s AND organizacao_id = %(organizacao_id)s",
        dados,
    )


def excluir_lancamento(lancamento_id, organizacao_id):
    execute(
        "DELETE FROM lancamentos WHERE id = %s AND organizacao_id = %s",
        (lancamento_id, organizacao_id),
    )


def listar_lancamentos(organizacao_id, filtros=None):
    filtros = filtros or {}
    sql = """SELECT l.*, c.nome AS categoria_nome, sc.nome AS subcategoria_nome,
                    fp.nome AS forma_pagamento_nome, p.nome AS pessoa_nome, ca.nome AS cartao_nome
             FROM lancamentos l
             LEFT JOIN categorias c ON c.id = l.categoria_id
             LEFT JOIN subcategorias sc ON sc.id = l.subcategoria_id
             LEFT JOIN formas_pagamento fp ON fp.id = l.forma_pagamento_id
             LEFT JOIN pessoas p ON p.id = l.pessoa_id
             LEFT JOIN cartoes ca ON ca.id = l.cartao_id
             WHERE l.organizacao_id = %(organizacao_id)s"""
    params = {"organizacao_id": organizacao_id}

    if filtros.get("data_inicio"):
        sql += " AND l.data >= %(data_inicio)s"
        params["data_inicio"] = filtros["data_inicio"]
    if filtros.get("data_fim"):
        sql += " AND l.data <= %(data_fim)s"
        params["data_fim"] = filtros["data_fim"]
    if filtros.get("tipo"):
        sql += " AND l.tipo = %(tipo)s"
        params["tipo"] = filtros["tipo"]
    if filtros.get("categoria_id"):
        sql += " AND l.categoria_id = %(categoria_id)s"
        params["categoria_id"] = filtros["categoria_id"]
    if filtros.get("forma_pagamento_id"):
        sql += " AND l.forma_pagamento_id = %(forma_pagamento_id)s"
        params["forma_pagamento_id"] = filtros["forma_pagamento_id"]
    if filtros.get("cartao_id"):
        sql += " AND l.cartao_id = %(cartao_id)s"
        params["cartao_id"] = filtros["cartao_id"]
    if filtros.get("pessoa_id"):
        sql += " AND l.pessoa_id = %(pessoa_id)s"
        params["pessoa_id"] = filtros["pessoa_id"]
    if filtros.get("busca"):
        sql += " AND l.descricao ILIKE %(busca)s"
        params["busca"] = f"%{filtros['busca']}%"

    sql += " ORDER BY l.data DESC, l.id DESC"
    return query_all(sql, params)


def totais_mes(organizacao_id, mes_referencia):
    row = query_one(
        """SELECT
             COALESCE(SUM(CASE WHEN tipo='receita' THEN valor ELSE 0 END), 0) AS receitas,
             COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor ELSE 0 END), 0) AS despesas
           FROM lancamentos
           WHERE organizacao_id = %s AND to_char(data, 'YYYY-MM') = %s""",
        (organizacao_id, mes_referencia),
    )
    receitas = float(row["receitas"])
    despesas = float(row["despesas"])
    return {"receitas": receitas, "despesas": despesas, "saldo": receitas - despesas}


def ultimos_lancamentos(organizacao_id, limite=5):
    return query_all(
        """SELECT l.*, c.nome AS categoria_nome
           FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id
           WHERE l.organizacao_id = %s ORDER BY l.data DESC, l.id DESC LIMIT %s""",
        (organizacao_id, limite),
    )


# ---------- Lançamentos recorrentes (templates) ----------

def listar_templates_recorrentes(organizacao_id):
    return query_all(
        """SELECT t.*, c.nome AS categoria_nome, fp.nome AS forma_pagamento_nome
           FROM lancamentos_recorrentes_templates t
           LEFT JOIN categorias c ON c.id = t.categoria_id
           LEFT JOIN formas_pagamento fp ON fp.id = t.forma_pagamento_id
           WHERE t.organizacao_id = %s AND t.ativo = true ORDER BY t.nome""",
        (organizacao_id,),
    )


def criar_template_recorrente(organizacao_id, dados):
    return execute(
        """INSERT INTO lancamentos_recorrentes_templates
             (organizacao_id, nome, valor, categoria_id, forma_pagamento_id, frequencia)
           VALUES (%(organizacao_id)s, %(nome)s, %(valor)s, %(categoria_id)s,
                   %(forma_pagamento_id)s, %(frequencia)s) RETURNING *""",
        {**dados, "organizacao_id": organizacao_id},
    )


def buscar_template_recorrente(template_id, organizacao_id):
    return query_one(
        "SELECT * FROM lancamentos_recorrentes_templates WHERE id = %s AND organizacao_id = %s",
        (template_id, organizacao_id),
    )


def excluir_template_recorrente(template_id, organizacao_id):
    execute(
        "DELETE FROM lancamentos_recorrentes_templates WHERE id = %s AND organizacao_id = %s",
        (template_id, organizacao_id),
    )
