# -*- coding: utf-8 -*-
import psycopg
from psycopg.rows import dict_row
from flask import g
from datetime import date as _date
from dateutil.relativedelta import relativedelta as _rd
from config import Config


def get_conn():
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


# ---------- Usuários / Organizações ----------

def buscar_usuario_por_email(email):
    return query_one("SELECT * FROM usuarios WHERE email = %s", (email.strip().lower(),))


def criar_super_admin(email):
    return execute(
        """INSERT INTO usuarios (email, papel, status, criado_em)
           VALUES (%s, 'super_admin', 'ativo', now()) RETURNING *""",
        (email.strip().lower(),),
    )


def atualizar_login(usuario_id, google_sub, nome):
    execute(
        """UPDATE usuarios SET google_sub = %s, nome = COALESCE(nome, %s), ultimo_login_em = now()
           WHERE id = %s""",
        (google_sub, nome, usuario_id),
    )


def ativar_usuario_se_pendente(usuario_id):
    execute("UPDATE usuarios SET status = 'ativo' WHERE id = %s AND status = 'pendente'", (usuario_id,))


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
        "SELECT id, email, nome, papel, status, criado_em FROM usuarios WHERE organizacao_id = %s ORDER BY criado_em",
        (organizacao_id,),
    )


# ---------- Categorias / Formas de pagamento / Cartões / Pessoas ----------

CATEGORIAS_PADRAO_DESPESA = [
    "Moradia", "Alimentação", "Mercado", "Transporte", "Saúde",
    "Educação", "Lazer", "Assinaturas", "Vestuário", "Outros",
]
CATEGORIAS_PADRAO_RECEITA = ["Salário", "Freelance / Extra", "Investimentos", "Outras receitas"]
FORMAS_PAGAMENTO_PADRAO = [
    ("Dinheiro", "ambos", False), ("Débito", "despesa", False), ("Pix", "ambos", False),
    ("Boleto", "despesa", True), ("Cartão de Crédito", "despesa", True),
    ("Depósito em conta", "receita", False), ("Transferência recebida", "receita", False),
]


def seed_organizacao(organizacao_id):
    for i, nome in enumerate(CATEGORIAS_PADRAO_DESPESA):
        execute(
            "INSERT INTO categorias (organizacao_id, nome, ordem, tipo) VALUES (%s, %s, %s, 'despesa') "
            "ON CONFLICT (organizacao_id, nome) DO NOTHING",
            (organizacao_id, nome, i),
        )
    for i, nome in enumerate(CATEGORIAS_PADRAO_RECEITA):
        execute(
            "INSERT INTO categorias (organizacao_id, nome, ordem, tipo) VALUES (%s, %s, %s, 'receita') "
            "ON CONFLICT (organizacao_id, nome) DO NOTHING",
            (organizacao_id, nome, i),
        )
    for nome, aplica_a, permite_parc in FORMAS_PAGAMENTO_PADRAO:
        execute(
            "INSERT INTO formas_pagamento (organizacao_id, nome, aplica_a, permite_parcelamento, padrao) "
            "VALUES (%s, %s, %s, %s, true)",
            (organizacao_id, nome, aplica_a, permite_parc),
        )


def listar_categorias(organizacao_id, apenas_ativas=True, tipo=None):
    sql = "SELECT * FROM categorias WHERE organizacao_id = %s"
    params = [organizacao_id]
    if apenas_ativas:
        sql += " AND ativa = true"
    if tipo:
        sql += " AND tipo IN (%s, 'ambos')"
        params.append(tipo)
    sql += " ORDER BY ordem, nome"
    return query_all(sql, params)


def listar_subcategorias(categoria_id):
    return query_all(
        "SELECT * FROM subcategorias WHERE categoria_id = %s AND ativa = true ORDER BY nome",
        (categoria_id,),
    )


def listar_formas_pagamento(organizacao_id, tipo=None):
    sql = "SELECT * FROM formas_pagamento WHERE organizacao_id = %s AND ativa = true"
    params = [organizacao_id]
    if tipo:
        sql += " AND aplica_a IN (%s, 'ambos')"
        params.append(tipo)
    sql += " ORDER BY nome"
    return query_all(sql, params)


def listar_cartoes(organizacao_id):
    return query_all(
        "SELECT * FROM cartoes WHERE organizacao_id = %s AND ativo = true ORDER BY nome",
        (organizacao_id,),
    )


def listar_pessoas(organizacao_id, apenas_disponiveis_lancamento=True):
    sql = "SELECT * FROM pessoas WHERE organizacao_id = %s"
    if apenas_disponiveis_lancamento:
        sql += " AND disponivel_lancamento = true"
    sql += " ORDER BY nome"
    return query_all(sql, (organizacao_id,))


def sugerir_categoria_por_descricao(organizacao_id, descricao):
    if not descricao:
        return None
    categorias = listar_categorias(organizacao_id)
    desc = descricao.lower()
    encontradas = []
    for cat in categorias:
        if not cat["palavras_chave"]:
            continue
        palavras = [pv.strip().lower() for pv in cat["palavras_chave"].split(",") if pv.strip()]
        if any(pv in desc for pv in palavras):
            encontradas.append(cat["id"])
    return encontradas[0] if len(encontradas) == 1 else None


# ---------- Lançamentos ----------

def criar_lancamento(organizacao_id, dados, criado_por):
    dados = {**dados, "taxa_juros_mensal": dados.get("taxa_juros_mensal")}
    return execute(
        """INSERT INTO lancamentos
             (organizacao_id, data, tipo, valor, descricao, categoria_id, subcategoria_id,
              forma_pagamento_id, cartao_id, pessoa_id, grupo_parcelamento_id,
              parcela_atual, parcela_total, observacao, taxa_juros_mensal, criado_por, criado_em)
           VALUES (%(organizacao_id)s, %(data)s, %(tipo)s, %(valor)s, %(descricao)s,
                   %(categoria_id)s, %(subcategoria_id)s, %(forma_pagamento_id)s,
                   %(cartao_id)s, %(pessoa_id)s, %(grupo_parcelamento_id)s,
                   %(parcela_atual)s, %(parcela_total)s, %(observacao)s, %(taxa_juros_mensal)s,
                   %(criado_por)s, now())
           RETURNING *""",
        {**dados, "organizacao_id": organizacao_id, "criado_por": criado_por},
    )


def buscar_lancamento(lancamento_id, organizacao_id):
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
    execute("DELETE FROM lancamentos WHERE id = %s AND organizacao_id = %s", (lancamento_id, organizacao_id))


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
        sql += " AND l.data >= %(data_inicio)s"; params["data_inicio"] = filtros["data_inicio"]
    if filtros.get("data_fim"):
        sql += " AND l.data <= %(data_fim)s"; params["data_fim"] = filtros["data_fim"]
    if filtros.get("tipo"):
        sql += " AND l.tipo = %(tipo)s"; params["tipo"] = filtros["tipo"]
    if filtros.get("categoria_id"):
        sql += " AND l.categoria_id = %(categoria_id)s"; params["categoria_id"] = filtros["categoria_id"]
    if filtros.get("forma_pagamento_id"):
        sql += " AND l.forma_pagamento_id = %(forma_pagamento_id)s"; params["forma_pagamento_id"] = filtros["forma_pagamento_id"]
    if filtros.get("cartao_id"):
        sql += " AND l.cartao_id = %(cartao_id)s"; params["cartao_id"] = filtros["cartao_id"]
    if filtros.get("pessoa_id"):
        sql += " AND l.pessoa_id = %(pessoa_id)s"; params["pessoa_id"] = filtros["pessoa_id"]
    if filtros.get("busca"):
        sql += " AND l.descricao ILIKE %(busca)s"; params["busca"] = f"%{filtros['busca']}%"
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
    receitas = float(row["receitas"]); despesas = float(row["despesas"])
    return {"receitas": receitas, "despesas": despesas, "saldo": receitas - despesas}


def ultimos_lancamentos(organizacao_id, limite=5):
    return query_all(
        """SELECT l.*, c.nome AS categoria_nome FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id
           WHERE l.organizacao_id = %s ORDER BY l.data DESC, l.id DESC LIMIT %s""",
        (organizacao_id, limite),
    )


# ---------- Lançamentos recorrentes ----------

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
           VALUES (%(organizacao_id)s, %(nome)s, %(valor)s, %(categoria_id)s, %(forma_pagamento_id)s, %(frequencia)s)
           RETURNING *""",
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


# ---------- Anexos de lançamento ----------

def salvar_anexo(lancamento_id, nome_arquivo, mimetype, conteudo_bytes):
    return execute(
        """INSERT INTO lancamentos_anexos (lancamento_id, nome_arquivo, mimetype, conteudo, tamanho_bytes, criado_em)
           VALUES (%s, %s, %s, %s, %s, now()) RETURNING id""",
        (lancamento_id, nome_arquivo, mimetype, conteudo_bytes, len(conteudo_bytes)),
    )


def buscar_anexo(anexo_id, organizacao_id):
    return query_one(
        """SELECT a.* FROM lancamentos_anexos a JOIN lancamentos l ON l.id = a.lancamento_id
           WHERE a.id = %s AND l.organizacao_id = %s""",
        (anexo_id, organizacao_id),
    )


def anexo_id_por_lancamento(lancamento_ids):
    if not lancamento_ids:
        return {}
    rows = query_all(
        """SELECT DISTINCT ON (lancamento_id) lancamento_id, id AS anexo_id
           FROM lancamentos_anexos WHERE lancamento_id = ANY(%s) ORDER BY lancamento_id, criado_em""",
        (list(lancamento_ids),),
    )
    return {r["lancamento_id"]: r["anexo_id"] for r in rows}


# ---------- Planejamento / Controle ----------

def buscar_preferencias(organizacao_id):
    return query_one("SELECT * FROM organizacoes_preferencias WHERE organizacao_id = %s", (organizacao_id,))


def salvar_renda_mensal(organizacao_id, renda_mensal):
    execute("UPDATE organizacoes_preferencias SET renda_mensal = %s WHERE organizacao_id = %s",
            (renda_mensal, organizacao_id))


def listar_planejamento_mes(organizacao_id, mes_referencia):
    return query_all(
        """SELECT c.id AS categoria_id, c.nome AS categoria_nome, COALESCE(p.valor_limite, 0) AS valor_limite
           FROM categorias c
           LEFT JOIN planejamentos p ON p.categoria_id = c.id AND p.mes_referencia = %(mes)s
           WHERE c.organizacao_id = %(org)s AND c.ativa = true AND c.tipo IN ('despesa','ambos')
           ORDER BY c.ordem, c.nome""",
        {"org": organizacao_id, "mes": mes_referencia},
    )


def salvar_planejamento_categoria(organizacao_id, mes_referencia, categoria_id, valor_limite):
    execute(
        """INSERT INTO planejamentos (organizacao_id, mes_referencia, categoria_id, valor_limite)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (organizacao_id, mes_referencia, categoria_id) DO UPDATE SET valor_limite = excluded.valor_limite""",
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
    rows = query_all(
        """SELECT categoria_id, SUM(valor) AS total FROM (
             SELECT categoria_id, valor FROM lancamentos
               WHERE organizacao_id = %(org)s AND tipo = 'despesa' AND to_char(data, 'YYYY-MM') = %(mes)s
             UNION ALL
             SELECT lc.categoria_id, lc.valor FROM lancamentos_cartao lc
               JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
               WHERE c.organizacao_id = %(org)s AND lc.sinal = 'D' AND f.mes_referencia = %(mes)s
           ) t GROUP BY categoria_id""",
        {"org": organizacao_id, "mes": mes_referencia},
    )
    return {r["categoria_id"]: float(r["total"]) for r in rows if r["categoria_id"] is not None}


def gasto_medio_categoria_ultimos_meses(organizacao_id, mes_referencia, n_meses=3):
    ref = _date.fromisoformat(mes_referencia + "-01")
    totais = {}
    for i in range(1, n_meses + 1):
        mes = (ref - _rd(months=i)).strftime("%Y-%m")
        for cat_id, valor in realizado_por_categoria_mes(organizacao_id, mes).items():
            totais[cat_id] = totais.get(cat_id, 0) + valor
    return {cat_id: round(v / n_meses, 2) for cat_id, v in totais.items()}


def lancamentos_por_categoria_mes(organizacao_id, categoria_id, mes_referencia):
    gerais = query_all(
        """SELECT id, data, descricao, valor, forma_pagamento_id, pessoa_id, 'geral' AS origem
           FROM lancamentos WHERE organizacao_id = %(org)s AND categoria_id = %(cat)s AND tipo = 'despesa'
             AND to_char(data, 'YYYY-MM') = %(mes)s ORDER BY data DESC""",
        {"org": organizacao_id, "cat": categoria_id, "mes": mes_referencia},
    )
    cartao = query_all(
        """SELECT lc.id, lc.data_iso AS data, lc.descricao, lc.valor, NULL AS forma_pagamento_id,
                  lc.pessoa_id, 'cartao' AS origem
           FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %(org)s AND lc.categoria_id = %(cat)s AND lc.sinal = 'D'
             AND f.mes_referencia = %(mes)s ORDER BY lc.data_iso DESC""",
        {"org": organizacao_id, "cat": categoria_id, "mes": mes_referencia},
    )
    return list(gerais) + list(cartao)


# ---------- Cartão de Crédito ----------

def encontrar_ou_criar_pessoa(organizacao_id, nome, disponivel_lancamento=False):
    p = query_one("SELECT * FROM pessoas WHERE organizacao_id = %s AND nome = %s", (organizacao_id, nome))
    if p:
        return p
    return execute(
        "INSERT INTO pessoas (organizacao_id, nome, disponivel_lancamento, criado_em) VALUES (%s, %s, %s, now()) RETURNING *",
        (organizacao_id, nome, disponivel_lancamento),
    )


def encontrar_ou_criar_cartao_por_pessoa(organizacao_id, pessoa_id, nome_pessoa):
    """1 cartão por pessoa, não por número de cartão - a CAIXA (e outros
    bancos) reemitem números de cartão diferentes pra mesma pessoa ao longo
    do tempo, então consolidamos pelo titular, não pelo número."""
    c = query_one("SELECT * FROM cartoes WHERE organizacao_id = %s AND pessoa_id = %s", (organizacao_id, pessoa_id))
    if c:
        return c
    return execute(
        "INSERT INTO cartoes (organizacao_id, pessoa_id, nome, ativo) VALUES (%s, %s, %s, true) RETURNING *",
        (organizacao_id, pessoa_id, f"Cartão de {nome_pessoa}"),
    )


def salvar_fatura(cartao_id, dados, importado_por):
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
                 arquivo_origem=%(arquivo_origem)s, numero_cartao_origem=%(numero_cartao_origem)s,
                 importado_por=%(importado_por)s, importado_em=now()
               WHERE id=%(id)s""",
            {**dados, "importado_por": importado_por, "id": existente["id"]},
        )
        return existente["id"]
    row = execute(
        """INSERT INTO faturas (cartao_id, mes_referencia, vencimento, valor_total, valor_minimo,
             limite_total, limite_utilizado, limite_disponivel, arquivo_origem, numero_cartao_origem,
             importado_por, importado_em)
           VALUES (%(cartao_id)s, %(mes_referencia)s, %(vencimento)s, %(valor_total)s, %(valor_minimo)s,
                   %(limite_total)s, %(limite_utilizado)s, %(limite_disponivel)s, %(arquivo_origem)s,
                   %(numero_cartao_origem)s, %(importado_por)s, now())
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
                   %(parcela_atual)s, %(parcela_total)s, %(parcelada)s, %(tipo)s, %(categoria_id)s, %(pessoa_id)s)""",
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
        "SELECT f.id FROM faturas f JOIN cartoes c ON c.id = f.cartao_id WHERE f.id = %s AND c.organizacao_id = %s",
        (fatura_id, organizacao_id),
    )
    if fat:
        execute("DELETE FROM faturas WHERE id = %s", (fatura_id,))


def ultimas_faturas_por_cartao(organizacao_id):
    return query_all(
        """SELECT DISTINCT ON (c.id) f.*, c.nome AS cartao_nome
           FROM cartoes c JOIN faturas f ON f.cartao_id = c.id
           WHERE c.organizacao_id = %s ORDER BY c.id, f.mes_referencia DESC, f.id DESC""",
        (organizacao_id,),
    )


def listar_lancamentos_cartao(organizacao_id, filtros=None):
    filtros = filtros or {}
    sql = """SELECT lc.*, f.mes_referencia, c.nome AS cartao_nome, cat.nome AS categoria_nome, p.nome AS pessoa_nome
             FROM lancamentos_cartao lc
             JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
             LEFT JOIN categorias cat ON cat.id = lc.categoria_id LEFT JOIN pessoas p ON p.id = lc.pessoa_id
             WHERE c.organizacao_id = %(organizacao_id)s"""
    params = {"organizacao_id": organizacao_id}
    if filtros.get("mes_referencia"):
        sql += " AND f.mes_referencia = %(mes_referencia)s"; params["mes_referencia"] = filtros["mes_referencia"]
    if filtros.get("cartao_id"):
        sql += " AND c.id = %(cartao_id)s"; params["cartao_id"] = filtros["cartao_id"]
    if filtros.get("pessoa_id"):
        sql += " AND lc.pessoa_id = %(pessoa_id)s"; params["pessoa_id"] = filtros["pessoa_id"]
    if filtros.get("busca"):
        sql += " AND lc.descricao ILIKE %(busca)s"; params["busca"] = f"%{filtros['busca']}%"
    sql += " ORDER BY lc.data_iso DESC, lc.id DESC"
    return query_all(sql, params)


# ---------- Configurações: Categorias, Formas de Pagamento, Cartões, Pessoas, Usuários ----------

def listar_categorias_todas(organizacao_id):
    return query_all("SELECT * FROM categorias WHERE organizacao_id = %s ORDER BY tipo, ordem, nome", (organizacao_id,))


def criar_categoria(organizacao_id, nome, descricao, tipo, palavras_chave=None):
    return execute(
        """INSERT INTO categorias (organizacao_id, nome, descricao, tipo, palavras_chave, ativa)
           VALUES (%s, %s, %s, %s, %s, true) RETURNING *""",
        (organizacao_id, nome, descricao, tipo, palavras_chave),
    )


def atualizar_categoria(categoria_id, organizacao_id, nome, descricao, tipo, palavras_chave, ativa):
    execute(
        "UPDATE categorias SET nome=%s, descricao=%s, tipo=%s, palavras_chave=%s, ativa=%s WHERE id=%s AND organizacao_id=%s",
        (nome, descricao, tipo, palavras_chave, ativa, categoria_id, organizacao_id),
    )


def excluir_categoria(categoria_id, organizacao_id):
    execute("DELETE FROM categorias WHERE id=%s AND organizacao_id=%s", (categoria_id, organizacao_id))


def listar_formas_pagamento_todas(organizacao_id):
    return query_all("SELECT * FROM formas_pagamento WHERE organizacao_id = %s ORDER BY aplica_a, nome", (organizacao_id,))


def criar_forma_pagamento(organizacao_id, nome, aplica_a, permite_parcelamento):
    return execute(
        "INSERT INTO formas_pagamento (organizacao_id, nome, aplica_a, permite_parcelamento, ativa) VALUES (%s, %s, %s, %s, true) RETURNING *",
        (organizacao_id, nome, aplica_a, permite_parcelamento),
    )


def atualizar_forma_pagamento(fp_id, organizacao_id, nome, aplica_a, permite_parcelamento, ativa):
    execute(
        "UPDATE formas_pagamento SET nome=%s, aplica_a=%s, permite_parcelamento=%s, ativa=%s WHERE id=%s AND organizacao_id=%s",
        (nome, aplica_a, permite_parcelamento, ativa, fp_id, organizacao_id),
    )


def excluir_forma_pagamento(fp_id, organizacao_id):
    execute("DELETE FROM formas_pagamento WHERE id=%s AND organizacao_id=%s", (fp_id, organizacao_id))


def listar_cartoes_todos(organizacao_id):
    return query_all(
        """SELECT c.*, p.nome AS pessoa_nome FROM cartoes c LEFT JOIN pessoas p ON p.id = c.pessoa_id
           WHERE c.organizacao_id = %s ORDER BY c.nome""",
        (organizacao_id,),
    )


def criar_cartao_manual(organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, pessoa_id=None):
    return execute(
        """INSERT INTO cartoes (organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, pessoa_id, ativo)
           VALUES (%s, %s, %s, %s, %s, %s, true) RETURNING *""",
        (organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, pessoa_id),
    )


def atualizar_cartao(cartao_id, organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, ativo, pessoa_id=None):
    execute(
        """UPDATE cartoes SET nome=%s, limite_total=%s, dia_fechamento=%s, dia_vencimento=%s, ativo=%s, pessoa_id=%s
           WHERE id=%s AND organizacao_id=%s""",
        (nome, limite_total, dia_fechamento, dia_vencimento, ativo, pessoa_id, cartao_id, organizacao_id),
    )


def excluir_cartao(cartao_id, organizacao_id):
    execute("DELETE FROM cartoes WHERE id=%s AND organizacao_id=%s", (cartao_id, organizacao_id))


def listar_pessoas_todas(organizacao_id):
    return query_all(
        """SELECT p.*, u.email AS usuario_email FROM pessoas p LEFT JOIN usuarios u ON u.id = p.usuario_id
           WHERE p.organizacao_id = %s ORDER BY p.nome""",
        (organizacao_id,),
    )


def criar_pessoa_manual(organizacao_id, nome, usuario_id=None):
    return execute(
        "INSERT INTO pessoas (organizacao_id, nome, usuario_id, disponivel_lancamento, criado_em) "
        "VALUES (%s, %s, %s, true, now()) RETURNING *",
        (organizacao_id, nome, usuario_id),
    )


def atualizar_pessoa(pessoa_id, organizacao_id, nome, usuario_id, disponivel_lancamento):
    execute(
        "UPDATE pessoas SET nome=%s, usuario_id=%s, disponivel_lancamento=%s WHERE id=%s AND organizacao_id=%s",
        (nome, usuario_id, disponivel_lancamento, pessoa_id, organizacao_id),
    )


def excluir_pessoa(pessoa_id, organizacao_id):
    execute("DELETE FROM pessoas WHERE id=%s AND organizacao_id=%s", (pessoa_id, organizacao_id))


def convidar_usuario_organizacao(organizacao_id, email, papel, convidado_por):
    return execute(
        """INSERT INTO usuarios (organizacao_id, email, papel, status, convidado_por, criado_em)
           VALUES (%s, %s, %s, 'pendente', %s, now()) RETURNING *""",
        (organizacao_id, email.strip().lower(), papel, convidado_por),
    )


def remover_usuario_organizacao(usuario_id, organizacao_id):
    execute("DELETE FROM usuarios WHERE id=%s AND organizacao_id=%s", (usuario_id, organizacao_id))


def bloquear_usuario_organizacao(usuario_id, organizacao_id):
    execute("UPDATE usuarios SET status='bloqueado' WHERE id=%s AND organizacao_id=%s", (usuario_id, organizacao_id))


def reativar_usuario_organizacao(usuario_id, organizacao_id):
    execute("UPDATE usuarios SET status='ativo' WHERE id=%s AND organizacao_id=%s", (usuario_id, organizacao_id))


def buscar_categoria_por_nome(organizacao_id, nome):
    return query_one("SELECT id FROM categorias WHERE organizacao_id = %s AND nome = %s", (organizacao_id, nome))
