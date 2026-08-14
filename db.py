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


# ---------- Cartão de Crédito (importação de fatura) ----------

def encontrar_ou_criar_pessoa(organizacao_id, nome):
    p = query_one("SELECT * FROM pessoas WHERE organizacao_id = %s AND nome = %s", (organizacao_id, nome))
    if p:
        return p
    return execute(
        "INSERT INTO pessoas (organizacao_id, nome, criado_em) VALUES (%s, %s, now()) RETURNING *",
        (organizacao_id, nome),
    )


def encontrar_ou_criar_cartao_por_nome(organizacao_id, nome):
    c = query_one("SELECT * FROM cartoes WHERE organizacao_id = %s AND nome = %s", (organizacao_id, nome))
    if c:
        return c
    return execute(
        "INSERT INTO cartoes (organizacao_id, nome, ativo) VALUES (%s, %s, true) RETURNING *",
        (organizacao_id, nome),
    )


def buscar_categoria_por_nome(organizacao_id, nome):
    return query_one("SELECT id FROM categorias WHERE organizacao_id = %s AND nome = %s", (organizacao_id, nome))


def salvar_fatura(cartao_id, dados, importado_por):
    """Cria ou atualiza a fatura (cartao_id + mes_referencia é único). Se já
    existir (reimportação do mesmo mês), apaga os lançamentos antigos dela
    antes de inserir os novos, pra não duplicar."""
    existente = query_one(
        "SELECT id FROM faturas WHERE cartao_id = %s AND mes_referencia = %s",
        (cartao_id, dados["mes_referencia"]),
    )
    if existente:
        execute("DELETE FROM lancamentos_cartao WHERE fatura_id = %s", (existente["id"],))
        execute(
            """UPDATE faturas SET vencimento=%(vencimento)s, valor_total=%(valor_total)s,
                 valor_minimo=%(valor_minimo)s, limite_total=%(limite_total)s,
                 limite_utilizado=%(limite_utilizado)s, limite_disponivel=%(limite_disponivel)s,
                 arquivo_origem=%(arquivo_origem)s, importado_por=%(importado_por)s, importado_em=now()
               WHERE id=%(id)s""",
            {**dados, "importado_por": importado_por, "id": existente["id"]},
        )
        return existente["id"]
    row = execute(
        """INSERT INTO faturas (cartao_id, mes_referencia, vencimento, valor_total, valor_minimo,
             limite_total, limite_utilizado, limite_disponivel, arquivo_origem, importado_por, importado_em)
           VALUES (%(cartao_id)s, %(mes_referencia)s, %(vencimento)s, %(valor_total)s, %(valor_minimo)s,
                   %(limite_total)s, %(limite_utilizado)s, %(limite_disponivel)s, %(arquivo_origem)s,
                   %(importado_por)s, now())
           RETURNING id""",
        {**dados, "cartao_id": cartao_id, "importado_por": importado_por},
    )
    return row["id"]


def inserir_lancamento_cartao(fatura_id, dados):
    execute(
        """INSERT INTO lancamentos_cartao
             (fatura_id, data_iso, descricao, cidade, valor, sinal, parcela_atual,
              parcela_total, parcelada, tipo, categoria_id, pessoa_id)
           VALUES (%(fatura_id)s, %(data_iso)s, %(descricao)s, %(cidade)s, %(valor)s, %(sinal)s,
                   %(parcela_atual)s, %(parcela_total)s, %(parcelada)s, %(tipo)s,
                   %(categoria_id)s, %(pessoa_id)s)""",
        {**dados, "fatura_id": fatura_id},
    )


def listar_faturas_organizacao(organizacao_id):
    return query_all(
        """SELECT f.*, c.nome AS cartao_nome,
                  (SELECT COUNT(*) FROM lancamentos_cartao lc WHERE lc.fatura_id = f.id) AS n_transacoes
           FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %s ORDER BY f.mes_referencia DESC, f.id DESC""",
        (organizacao_id,),
    )


def excluir_fatura(fatura_id, organizacao_id):
    fat = query_one(
        """SELECT f.id FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE f.id = %s AND c.organizacao_id = %s""",
        (fatura_id, organizacao_id),
    )
    if fat:
        execute("DELETE FROM faturas WHERE id = %s", (fatura_id,))


def ultima_fatura_organizacao(organizacao_id):
    return query_one(
        """SELECT f.*, c.nome AS cartao_nome
           FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %s ORDER BY f.mes_referencia DESC, f.id DESC LIMIT 1""",
        (organizacao_id,),
    )


def listar_lancamentos_cartao(organizacao_id, filtros=None):
    filtros = filtros or {}
    sql = """SELECT lc.*, f.mes_referencia, c.nome AS cartao_nome, cat.nome AS categoria_nome,
                    p.nome AS pessoa_nome
             FROM lancamentos_cartao lc
             JOIN faturas f ON f.id = lc.fatura_id
             JOIN cartoes c ON c.id = f.cartao_id
             LEFT JOIN categorias cat ON cat.id = lc.categoria_id
             LEFT JOIN pessoas p ON p.id = lc.pessoa_id
             WHERE c.organizacao_id = %(organizacao_id)s"""
    params = {"organizacao_id": organizacao_id}
    if filtros.get("mes_referencia"):
        sql += " AND f.mes_referencia = %(mes_referencia)s"
        params["mes_referencia"] = filtros["mes_referencia"]
    if filtros.get("cartao_id"):
        sql += " AND c.id = %(cartao_id)s"
        params["cartao_id"] = filtros["cartao_id"]
    if filtros.get("pessoa_id"):
        sql += " AND lc.pessoa_id = %(pessoa_id)s"
        params["pessoa_id"] = filtros["pessoa_id"]
    if filtros.get("busca"):
        sql += " AND lc.descricao ILIKE %(busca)s"
        params["busca"] = f"%{filtros['busca']}%"
    sql += " ORDER BY lc.data_iso DESC, lc.id DESC"
    return query_all(sql, params)


# ---------- Planejamento / Controle ----------

def buscar_preferencias(organizacao_id):
    return query_one("SELECT * FROM organizacoes_preferencias WHERE organizacao_id = %s", (organizacao_id,))


def salvar_renda_mensal(organizacao_id, renda_mensal):
    execute(
        "UPDATE organizacoes_preferencias SET renda_mensal = %s WHERE organizacao_id = %s",
        (renda_mensal, organizacao_id),
    )


def listar_planejamento_mes(organizacao_id, mes_referencia):
    """Todas as categorias ativas, com o valor planejado daquele mês (0 se
    ainda não foi definido)."""
    return query_all(
        """SELECT c.id AS categoria_id, c.nome AS categoria_nome,
                  COALESCE(p.valor_limite, 0) AS valor_limite
           FROM categorias c
           LEFT JOIN planejamentos p ON p.categoria_id = c.id AND p.mes_referencia = %(mes)s
           WHERE c.organizacao_id = %(org)s AND c.ativa = true
           ORDER BY c.ordem, c.nome""",
        {"org": organizacao_id, "mes": mes_referencia},
    )


def salvar_planejamento_categoria(organizacao_id, mes_referencia, categoria_id, valor_limite):
    execute(
        """INSERT INTO planejamentos (organizacao_id, mes_referencia, categoria_id, valor_limite)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (organizacao_id, mes_referencia, categoria_id)
           DO UPDATE SET valor_limite = excluded.valor_limite""",
        (organizacao_id, mes_referencia, categoria_id, valor_limite),
    )


def copiar_planejamento(organizacao_id, mes_origem, mes_destino):
    origem = query_all(
        "SELECT categoria_id, valor_limite FROM planejamentos WHERE organizacao_id = %s AND mes_referencia = %s",
        (organizacao_id, mes_origem),
    )
    for row in origem:
        salvar_planejamento_categoria(organizacao_id, mes_destino, row["categoria_id"], row["valor_limite"])
    return len(origem)


def realizado_por_categoria_mes(organizacao_id, mes_referencia):
    """{categoria_id: valor_realizado} somando lancamentos (geral) + lancamentos_cartao
    (cartão), só despesas, do mês."""
    rows = query_all(
        """SELECT categoria_id, SUM(valor) AS total FROM (
             SELECT categoria_id, valor FROM lancamentos
               WHERE organizacao_id = %(org)s AND tipo = 'despesa'
                 AND to_char(data, 'YYYY-MM') = %(mes)s
             UNION ALL
             SELECT lc.categoria_id, lc.valor FROM lancamentos_cartao lc
               JOIN faturas f ON f.id = lc.fatura_id
               JOIN cartoes c ON c.id = f.cartao_id
               WHERE c.organizacao_id = %(org)s AND lc.sinal = 'D' AND f.mes_referencia = %(mes)s
           ) t
           GROUP BY categoria_id""",
        {"org": organizacao_id, "mes": mes_referencia},
    )
    return {r["categoria_id"]: float(r["total"]) for r in rows if r["categoria_id"] is not None}


def lancamentos_por_categoria_mes(organizacao_id, categoria_id, mes_referencia):
    """Para o drill-down do Controle: todos os lançamentos (gerais + cartão)
    daquela categoria naquele mês."""
    gerais = query_all(
        """SELECT data, descricao, valor, forma_pagamento_id, pessoa_id, 'geral' AS origem
           FROM lancamentos
           WHERE organizacao_id = %(org)s AND categoria_id = %(cat)s AND tipo = 'despesa'
             AND to_char(data, 'YYYY-MM') = %(mes)s
           ORDER BY data DESC""",
        {"org": organizacao_id, "cat": categoria_id, "mes": mes_referencia},
    )
    cartao = query_all(
        """SELECT lc.data_iso AS data, lc.descricao, lc.valor, NULL AS forma_pagamento_id,
                  lc.pessoa_id, 'cartao' AS origem
           FROM lancamentos_cartao lc
           JOIN faturas f ON f.id = lc.fatura_id
           JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %(org)s AND lc.categoria_id = %(cat)s
             AND lc.sinal = 'D' AND f.mes_referencia = %(mes)s
           ORDER BY lc.data_iso DESC""",
        {"org": organizacao_id, "cat": categoria_id, "mes": mes_referencia},
    )
    return list(gerais) + list(cartao)


# ---------- Anexos de lançamento (comprovantes, cupons, fotos) ----------

def salvar_anexo(lancamento_id, nome_arquivo, mimetype, conteudo_bytes):
    return execute(
        """INSERT INTO lancamentos_anexos (lancamento_id, nome_arquivo, mimetype, conteudo, tamanho_bytes, criado_em)
           VALUES (%s, %s, %s, %s, %s, now()) RETURNING id""",
        (lancamento_id, nome_arquivo, mimetype, conteudo_bytes, len(conteudo_bytes)),
    )


def listar_anexos_lancamento(lancamento_id):
    return query_all(
        "SELECT id, nome_arquivo, mimetype, tamanho_bytes, criado_em FROM lancamentos_anexos "
        "WHERE lancamento_id = %s ORDER BY criado_em",
        (lancamento_id,),
    )


def buscar_anexo(anexo_id, organizacao_id):
    """Sempre confere que o anexo pertence a um lançamento da própria
    organização, antes de servir o arquivo - evita um usuário de um cliente
    acessar o comprovante de outro só sabendo o id."""
    return query_one(
        """SELECT a.* FROM lancamentos_anexos a
           JOIN lancamentos l ON l.id = a.lancamento_id
           WHERE a.id = %s AND l.organizacao_id = %s""",
        (anexo_id, organizacao_id),
    )


def anexo_id_por_lancamento(lancamento_ids):
    """{lancamento_id: anexo_id} do primeiro anexo de cada lançamento -
    usado no Extrato pra mostrar o clipe só nas linhas que têm anexo, com
    o link já pronto, sem 1 consulta por linha."""
    if not lancamento_ids:
        return {}
    rows = query_all(
        """SELECT DISTINCT ON (lancamento_id) lancamento_id, id AS anexo_id
           FROM lancamentos_anexos WHERE lancamento_id = ANY(%s)
           ORDER BY lancamento_id, criado_em""",
        (list(lancamento_ids),),
    )
    return {r["lancamento_id"]: r["anexo_id"] for r in rows}
