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
    "Educação", "Lazer", "Assinaturas", "Vestuário", "Encargos financeiros", "Outros",
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
    dados = {**dados, "taxa_juros_mensal": dados.get("taxa_juros_mensal"), "conta_bancaria_id": dados.get("conta_bancaria_id"), "destino_empresa_id": dados.get("destino_empresa_id")}
    return execute(
        """INSERT INTO lancamentos
             (organizacao_id, data, tipo, valor, descricao, categoria_id, subcategoria_id,
              forma_pagamento_id, cartao_id, pessoa_id, grupo_parcelamento_id,
              parcela_atual, parcela_total, observacao, taxa_juros_mensal, conta_bancaria_id, destino_empresa_id, criado_por, criado_em)
           VALUES (%(organizacao_id)s, %(data)s, %(tipo)s, %(valor)s, %(descricao)s,
                   %(categoria_id)s, %(subcategoria_id)s, %(forma_pagamento_id)s,
                   %(cartao_id)s, %(pessoa_id)s, %(grupo_parcelamento_id)s,
                   %(parcela_atual)s, %(parcela_total)s, %(observacao)s, %(taxa_juros_mensal)s,
                   %(conta_bancaria_id)s, %(destino_empresa_id)s, %(criado_por)s, now())
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
              "forma_pagamento_id", "cartao_id", "pessoa_id", "observacao", "destino_empresa_id"]
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
                    fp.nome AS forma_pagamento_nome, p.nome AS pessoa_nome, p.avatar AS pessoa_avatar, ca.nome AS cartao_nome, en.nome AS destino_nome
             FROM lancamentos l
             LEFT JOIN empresas en ON en.id = l.destino_empresa_id
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


def listar_planejamento_mes(organizacao_id, mes_referencia, tipo="despesa"):
    return query_all(
        """SELECT c.id AS categoria_id, c.nome AS categoria_nome, COALESCE(p.valor_limite, 0) AS valor_limite
           FROM categorias c
           LEFT JOIN planejamentos p ON p.categoria_id = c.id AND p.mes_referencia = %(mes)s
           WHERE c.organizacao_id = %(org)s AND c.ativa = true AND c.tipo IN (%(tipo)s, 'ambos')
           ORDER BY c.ordem, c.nome""",
        {"org": organizacao_id, "mes": mes_referencia, "tipo": tipo},
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


def historico_por_categoria(organizacao_id, mes_referencia, n_meses=3):
    """Média por categoria dos n meses ANTERIORES ao mês. Conta só os meses em que houve gasto: mês sem nenhum
    dado é fatura ou lançamento ainda não importado, não 'gastei zero' (senão a média sairia dividida à toa).
    Devolve {'medias': {categoria_id: média}, 'sem_categoria': média, 'meses': [meses usados]}."""
    ref = _date.fromisoformat(mes_referencia + "-01")
    usados, totais, sem_categoria = [], {}, 0.0
    for i in range(1, n_meses + 1):
        mes = (ref - _rd(months=i)).strftime("%Y-%m")
        por_categoria = realizado_por_categoria_mes(organizacao_id, mes, incluir_sem_categoria=True)
        if sum(por_categoria.values()) <= 0:
            continue
        usados.append(mes)
        for cat_id, valor in por_categoria.items():
            if cat_id is None:
                sem_categoria += valor
            else:
                totais[cat_id] = totais.get(cat_id, 0) + valor
    n = len(usados)
    return {"medias": {c: round(v / n, 2) for c, v in totais.items()} if n else {},
            "sem_categoria": round(sem_categoria / n, 2) if n else 0.0, "meses": sorted(usados)}


def gasto_medio_categoria_ultimos_meses(organizacao_id, mes_referencia, n_meses=3):
    return historico_por_categoria(organizacao_id, mes_referencia, n_meses)["medias"]


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
                 importado_por=%(importado_por)s, importado_em=now(), previa=%(previa)s
               WHERE id=%(id)s""",
            {**dados, "importado_por": importado_por, "id": existente["id"], "previa": bool(dados.get("previa"))},
        )
        return existente["id"]
    row = execute(
        """INSERT INTO faturas (cartao_id, mes_referencia, vencimento, valor_total, valor_minimo,
             limite_total, limite_utilizado, limite_disponivel, arquivo_origem, numero_cartao_origem,
             importado_por, importado_em, previa)
           VALUES (%(cartao_id)s, %(mes_referencia)s, %(vencimento)s, %(valor_total)s, %(valor_minimo)s,
                   %(limite_total)s, %(limite_utilizado)s, %(limite_disponivel)s, %(arquivo_origem)s,
                   %(numero_cartao_origem)s, %(importado_por)s, now(), %(previa)s)
           RETURNING id""",
        {**dados, "cartao_id": cartao_id, "importado_por": importado_por, "previa": bool(dados.get("previa"))},
    )
    return row["id"]


def inserir_lancamento_cartao(fatura_id, dados):
    execute(
        """INSERT INTO lancamentos_cartao
             (fatura_id, data_iso, descricao, cidade, valor, sinal, parcela_atual,
              parcela_total, parcelada, tipo, categoria_id, pessoa_id, fornecedor, destino_empresa_id)
           VALUES (%(fatura_id)s, %(data_iso)s, %(descricao)s, %(cidade)s, %(valor)s, %(sinal)s,
                   %(parcela_atual)s, %(parcela_total)s, %(parcelada)s, %(tipo)s, %(categoria_id)s, %(pessoa_id)s, %(fornecedor)s, %(destino_empresa_id)s)""",
        {**dados, "fatura_id": fatura_id, "fornecedor": dados.get("fornecedor"), "destino_empresa_id": dados.get("destino_empresa_id")},
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
    sql = """SELECT lc.*, f.mes_referencia, c.nome AS cartao_nome, cat.nome AS categoria_nome, p.nome AS pessoa_nome,
                    COALESCE(NULLIF(TRIM(lc.fornecedor), ''), lc.descricao) AS fornecedor_exibicao, en.nome AS destino_nome
             FROM lancamentos_cartao lc
             JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
             LEFT JOIN empresas en ON en.id = lc.destino_empresa_id
             LEFT JOIN categorias cat ON cat.id = lc.categoria_id LEFT JOIN pessoas p ON p.id = lc.pessoa_id
             WHERE c.organizacao_id = %(organizacao_id)s AND COALESCE(lc.tipo, '') NOT IN ('SALDO_ANTERIOR', 'PAGAMENTO')"""
    params = {"organizacao_id": organizacao_id}
    if filtros.get("mes_referencia"):
        sql += " AND " + _mes_expr(filtros.get("lente")) + " = %(mes_referencia)s"; params["mes_referencia"] = filtros["mes_referencia"]
    if filtros.get("cartao_id"):
        sql += " AND c.id = %(cartao_id)s"; params["cartao_id"] = filtros["cartao_id"]
    if filtros.get("pessoa_id"):
        sql += " AND lc.pessoa_id = %(pessoa_id)s"; params["pessoa_id"] = filtros["pessoa_id"]
    if filtros.get("busca"):
        sql += " AND lc.descricao ILIKE %(busca)s"; params["busca"] = f"%{filtros['busca']}%"
    if filtros.get("categoria_id"):
        if str(filtros["categoria_id"]) == "sem":
            sql += " AND lc.categoria_id IS NULL"
        else:
            sql += " AND lc.categoria_id = %(categoria_id)s"; params["categoria_id"] = filtros["categoria_id"]
    if filtros.get("fornecedor"):
        sql += " AND " + _FORN_SQL + " = %(fornecedor)s"; params["fornecedor"] = filtros["fornecedor"].strip().upper()
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


def criar_cartao_manual(organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, pessoa_id=None, dono_empresa_id=None):
    return execute(
        """INSERT INTO cartoes (organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, pessoa_id, ativo, dono_empresa_id)
           VALUES (%s, %s, %s, %s, %s, %s, true, %s) RETURNING *""",
        (organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, pessoa_id, dono_empresa_id),
    )


def atualizar_cartao(cartao_id, organizacao_id, nome, limite_total, dia_fechamento, dia_vencimento, ativo, pessoa_id=None, dono_empresa_id=None):
    execute(
        """UPDATE cartoes SET nome=%s, limite_total=%s, dia_fechamento=%s, dia_vencimento=%s, ativo=%s, pessoa_id=%s, dono_empresa_id=%s
           WHERE id=%s AND organizacao_id=%s""",
        (nome, limite_total, dia_fechamento, dia_vencimento, ativo, pessoa_id, dono_empresa_id, cartao_id, organizacao_id),
    )


def excluir_cartao(cartao_id, organizacao_id):
    execute("DELETE FROM cartoes WHERE id=%s AND organizacao_id=%s", (cartao_id, organizacao_id))


def listar_pessoas_todas(organizacao_id):
    return query_all(
        """SELECT p.*, u.email AS usuario_email FROM pessoas p LEFT JOIN usuarios u ON u.id = p.usuario_id
           WHERE p.organizacao_id = %s ORDER BY p.nome""",
        (organizacao_id,),
    )


def criar_pessoa_manual(organizacao_id, nome, usuario_id=None, avatar=None, data_nascimento=None):
    return execute(
        "INSERT INTO pessoas (organizacao_id, nome, usuario_id, avatar, data_nascimento, disponivel_lancamento, criado_em) "
        "VALUES (%s, %s, %s, %s, %s, true, now()) RETURNING *",
        (organizacao_id, nome, usuario_id, avatar, data_nascimento),
    )


def atualizar_pessoa(pessoa_id, organizacao_id, nome, usuario_id, disponivel_lancamento, avatar=None, data_nascimento=None):
    execute(
        "UPDATE pessoas SET nome=%s, usuario_id=%s, disponivel_lancamento=%s, avatar=%s, data_nascimento=%s "
        "WHERE id=%s AND organizacao_id=%s",
        (nome, usuario_id, disponivel_lancamento, avatar, data_nascimento, pessoa_id, organizacao_id),
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


# ---------- Metas ----------

def listar_metas(organizacao_id):
    return query_all(
        "SELECT * FROM metas WHERE organizacao_id = %s ORDER BY status, data_alvo NULLS LAST, criado_em DESC",
        (organizacao_id,),
    )


def total_reservado_metas(organizacao_id):
    """Soma do que já foi guardado em todas as metas - informativo apenas,
    NÃO entra como lançamento nem afeta Planejamento/Controle (guardar
    dinheiro numa meta é irregular por natureza, não faz sentido tratar
    como um "gasto mensal previsto" que pode "estourar")."""
    row = query_one("SELECT COALESCE(SUM(valor_atual), 0) AS total FROM metas WHERE organizacao_id = %s", (organizacao_id,))
    return float(row["total"]) if row else 0.0


def criar_meta(organizacao_id, nome, descricao, valor_alvo, data_alvo):
    return execute(
        """INSERT INTO metas (organizacao_id, nome, descricao, valor_alvo, valor_atual, data_alvo, status, criado_em)
           VALUES (%s, %s, %s, %s, 0, %s, 'em_andamento', now()) RETURNING *""",
        (organizacao_id, nome, descricao, valor_alvo, data_alvo),
    )


def buscar_meta(meta_id, organizacao_id):
    return query_one("SELECT * FROM metas WHERE id = %s AND organizacao_id = %s", (meta_id, organizacao_id))


def excluir_meta(meta_id, organizacao_id):
    execute("DELETE FROM metas WHERE id = %s AND organizacao_id = %s", (meta_id, organizacao_id))


def registrar_movimento_meta(meta_id, organizacao_id, valor, observacao):
    meta = buscar_meta(meta_id, organizacao_id)
    if not meta:
        return None
    execute(
        "INSERT INTO metas_movimentos (meta_id, valor, data, observacao) VALUES (%s, %s, CURRENT_DATE, %s)",
        (meta_id, valor, observacao),
    )
    novo_valor = float(meta["valor_atual"]) + valor
    novo_status = "concluida" if meta["valor_alvo"] and novo_valor >= float(meta["valor_alvo"]) else meta["status"]
    execute(
        "UPDATE metas SET valor_atual = %s, status = %s WHERE id = %s",
        (novo_valor, novo_status, meta_id),
    )
    return novo_status


def listar_movimentos_meta(meta_id):
    return query_all("SELECT * FROM metas_movimentos WHERE meta_id = %s ORDER BY data DESC, id DESC", (meta_id,))


# ---------- Contas bancárias ----------

def listar_contas_bancarias(organizacao_id, apenas_ativas=True):
    sql = "SELECT * FROM contas_bancarias WHERE organizacao_id = %s"
    if apenas_ativas:
        sql += " AND ativa = true"
    sql += " ORDER BY nome"
    return query_all(sql, (organizacao_id,))


def criar_conta_bancaria(organizacao_id, nome, tipo, saldo_inicial, dono_empresa_id=None):
    return execute(
        """INSERT INTO contas_bancarias (organizacao_id, nome, tipo, saldo_inicial, ativa, criado_em, dono_empresa_id)
           VALUES (%s, %s, %s, %s, true, now(), %s) RETURNING *""",
        (organizacao_id, nome, tipo, saldo_inicial, dono_empresa_id),
    )


def atualizar_conta_bancaria(conta_id, organizacao_id, nome, tipo, saldo_inicial, ativa, dono_empresa_id=None):
    execute(
        "UPDATE contas_bancarias SET nome=%s, tipo=%s, saldo_inicial=%s, ativa=%s, dono_empresa_id=%s WHERE id=%s AND organizacao_id=%s",
        (nome, tipo, saldo_inicial, ativa, dono_empresa_id, conta_id, organizacao_id),
    )


def excluir_conta_bancaria(conta_id, organizacao_id):
    execute("DELETE FROM contas_bancarias WHERE id = %s AND organizacao_id = %s", (conta_id, organizacao_id))


def saldo_atual_conta(conta_id, organizacao_id):
    conta = query_one("SELECT saldo_inicial FROM contas_bancarias WHERE id = %s AND organizacao_id = %s",
                       (conta_id, organizacao_id))
    if not conta:
        return None
    row = query_one(
        """SELECT COALESCE(SUM(CASE WHEN tipo='receita' THEN valor ELSE -valor END), 0) AS movimento
           FROM lancamentos WHERE conta_bancaria_id = %s AND organizacao_id = %s""",
        (conta_id, organizacao_id),
    )
    return float(conta["saldo_inicial"]) + float(row["movimento"])


# ---------- Setup guiado ----------

def marcar_setup_concluido(organizacao_id):
    execute("UPDATE organizacoes_preferencias SET setup_concluido = true WHERE organizacao_id = %s", (organizacao_id,))


def status_checklist_setup(organizacao_id):
    n_categorias = query_one("SELECT COUNT(*) AS n FROM categorias WHERE organizacao_id = %s AND ativa = true", (organizacao_id,))["n"]
    n_cartoes = query_one("SELECT COUNT(*) AS n FROM cartoes WHERE organizacao_id = %s AND ativo = true", (organizacao_id,))["n"]
    n_contas = query_one("SELECT COUNT(*) AS n FROM contas_bancarias WHERE organizacao_id = %s AND ativa = true", (organizacao_id,))["n"]
    n_pessoas = query_one("SELECT COUNT(*) AS n FROM pessoas WHERE organizacao_id = %s AND disponivel_lancamento = true", (organizacao_id,))["n"]
    prefs = buscar_preferencias(organizacao_id)
    return {
        "categorias": n_categorias > 0,
        "renda": bool(prefs and prefs["renda_mensal"]),
        "cartoes": n_cartoes > 0,
        "contas": n_contas > 0,
        "pessoas": n_pessoas > 0,
    }



# ---------- Barra de atalhos ----------

def salvar_nav_usuario(usuario_id, valor):
    execute("UPDATE usuarios SET nav_atalhos = %s WHERE id = %s", (valor, usuario_id))


def salvar_nav_padrao_org(organizacao_id, valor):
    execute("UPDATE organizacoes_preferencias SET nav_atalhos_padrao = %s WHERE organizacao_id = %s", (valor, organizacao_id))


# ---------- Notificações (sininho) ----------

def buscar_usuario_por_id(usuario_id):
    return query_one("SELECT * FROM usuarios WHERE id = %s", (usuario_id,))


def criar_notificacao(organizacao_id, usuario_id, tipo, titulo, mensagem=None, link=None):
    execute(
        "INSERT INTO notificacoes (organizacao_id, usuario_id, tipo, titulo, mensagem, link) VALUES (%s, %s, %s, %s, %s, %s)",
        (organizacao_id, usuario_id, tipo, titulo, mensagem, link),
    )


def contar_nao_lidas(usuario_id):
    row = query_one("SELECT COUNT(*) AS n FROM notificacoes WHERE usuario_id = %s AND lida = false", (usuario_id,))
    return int(row["n"]) if row and "n" in row else 0


def listar_notificacoes(usuario_id, limite=60):
    return query_all(
        "SELECT * FROM notificacoes WHERE usuario_id = %s ORDER BY criado_em DESC, id DESC LIMIT %s",
        (usuario_id, limite),
    )


def marcar_todas_lidas(usuario_id):
    execute("UPDATE notificacoes SET lida = true WHERE usuario_id = %s AND lida = false", (usuario_id,))


# ---------- Quem acompanha o quê (definido pelo admin) ----------

def listar_observacoes(organizacao_id, observador_id):
    return query_all(
        "SELECT * FROM alertas_observacao WHERE organizacao_id = %s AND observador_usuario_id = %s",
        (organizacao_id, observador_id),
    )


def salvar_observacoes(organizacao_id, observador_id, regras):
    """regras: lista de (observado_usuario_id|None, observado_pessoa_id|None, por_email).
    Substitui todas as regras desse observador."""
    execute("DELETE FROM alertas_observacao WHERE organizacao_id = %s AND observador_usuario_id = %s",
            (organizacao_id, observador_id))
    for usuario_id, pessoa_id, por_email in regras:
        execute(
            "INSERT INTO alertas_observacao (organizacao_id, observador_usuario_id, observado_usuario_id, "
            "observado_pessoa_id, por_email) VALUES (%s, %s, %s, %s, %s)",
            (organizacao_id, observador_id, usuario_id, pessoa_id, por_email),
        )


def regras_que_casam(organizacao_id, ator_usuario_id, pessoa_id):
    return query_all(
        """SELECT observador_usuario_id, por_email FROM alertas_observacao
           WHERE organizacao_id = %s AND (
                 (observado_usuario_id IS NULL AND observado_pessoa_id IS NULL)
              OR observado_usuario_id = %s
              OR (observado_pessoa_id IS NOT NULL AND observado_pessoa_id = %s))""",
        (organizacao_id, ator_usuario_id, pessoa_id),
    )


# ---------- Lembretes de vencimento ----------

def listar_lembretes(organizacao_id, usuario_id):
    return query_all(
        "SELECT * FROM lembretes_vencimento WHERE organizacao_id = %s AND usuario_id = %s ORDER BY dia_mes, nome",
        (organizacao_id, usuario_id),
    )


def criar_lembrete(organizacao_id, usuario_id, nome, dia_mes, dias_antes, valor_estimado, por_email):
    execute(
        "INSERT INTO lembretes_vencimento (organizacao_id, usuario_id, nome, dia_mes, dias_antes, valor_estimado, por_email) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (organizacao_id, usuario_id, nome, dia_mes, dias_antes, valor_estimado, por_email),
    )


def atualizar_lembrete(lembrete_id, usuario_id, nome, dia_mes, dias_antes, valor_estimado, por_email, ativo):
    execute(
        "UPDATE lembretes_vencimento SET nome=%s, dia_mes=%s, dias_antes=%s, valor_estimado=%s, por_email=%s, ativo=%s "
        "WHERE id=%s AND usuario_id=%s",
        (nome, dia_mes, dias_antes, valor_estimado, por_email, ativo, lembrete_id, usuario_id),
    )


def excluir_lembrete(lembrete_id, usuario_id):
    execute("DELETE FROM lembretes_vencimento WHERE id = %s AND usuario_id = %s", (lembrete_id, usuario_id))


def lembretes_ativos_org(organizacao_id):
    return query_all(
        """SELECT l.*, u.email AS usuario_email FROM lembretes_vencimento l
           JOIN usuarios u ON u.id = l.usuario_id
           WHERE l.organizacao_id = %s AND l.ativo = true AND u.status != 'bloqueado'""",
        (organizacao_id,),
    )


def marcar_disparo_lembrete(lembrete_id, data):
    execute("UPDATE lembretes_vencimento SET ultimo_disparo = %s WHERE id = %s", (data, lembrete_id))


def listar_ids_organizacoes_ativas():
    return [r["id"] for r in query_all("SELECT id FROM organizacoes WHERE status = 'ativo'")]



# ---------- Análise do cartão (resumo por mês, categoria, fornecedor, parcelas) ----------

_BASE_LC = """FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id
              JOIN cartoes c ON c.id = f.cartao_id
              LEFT JOIN categorias cat ON cat.id = lc.categoria_id
              WHERE c.organizacao_id = %s AND COALESCE(lc.tipo, '') NOT IN ('SALDO_ANTERIOR', 'PAGAMENTO')"""


def excluir_faturas_mes(organizacao_id, mes):
    execute(
        "DELETE FROM faturas WHERE mes_referencia = %s AND cartao_id IN (SELECT id FROM cartoes WHERE organizacao_id = %s)",
        (mes, organizacao_id),
    )



# ---------- Correções manuais do cartão ----------

# nome "canônico" do fornecedor: o que foi definido à mão/por regra, senão o texto da fatura
_FORN_SQL = "UPPER(TRIM(COALESCE(NULLIF(TRIM(lc.fornecedor), ''), lc.descricao)))"


def buscar_lancamento_cartao(lc_id, organizacao_id):
    return query_one(
        """SELECT lc.*, f.mes_referencia, f.cartao_id, c.nome AS cartao_nome,
                  COALESCE(NULLIF(TRIM(lc.fornecedor), ''), lc.descricao) AS fornecedor_exibicao
           FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
           WHERE lc.id = %s AND c.organizacao_id = %s""",
        (lc_id, organizacao_id),
    )


def _ajustar_total_fatura(fatura_id, delta):
    if delta:
        execute("UPDATE faturas SET valor_total = valor_total + %s WHERE id = %s", (delta, fatura_id))


def atualizar_lancamento_cartao(lc_id, organizacao_id, d):
    """Corrige a compra e acerta o total da fatura pela diferença de valor."""
    from decimal import Decimal
    antigo = buscar_lancamento_cartao(lc_id, organizacao_id)
    if not antigo:
        return False
    execute(
        """UPDATE lancamentos_cartao SET fornecedor = %s, data_iso = %s, valor = %s, categoria_id = %s,
                  pessoa_id = %s, parcela_atual = %s, parcela_total = %s, parcelada = %s, nao_projetar = %s, destino_empresa_id = %s
           WHERE id = %s""",
        (d["fornecedor"], d["data_iso"], d["valor"], d["categoria_id"], d["pessoa_id"], d["parcela_atual"],
         d["parcela_total"], bool(d["parcela_total"] and d["parcela_total"] > 1), bool(d["nao_projetar"]), d.get("destino_empresa_id"), lc_id),
    )
    sinal = 1 if antigo["sinal"] == "D" else -1
    delta = (Decimal(str(d["valor"])) - Decimal(antigo["valor"])).quantize(Decimal("0.01")) * sinal
    _ajustar_total_fatura(antigo["fatura_id"], delta)
    return True


def excluir_lancamento_cartao(lc_id, organizacao_id):
    antigo = buscar_lancamento_cartao(lc_id, organizacao_id)
    if not antigo:
        return False
    execute("DELETE FROM lancamentos_cartao WHERE id = %s", (lc_id,))
    _ajustar_total_fatura(antigo["fatura_id"], -antigo["valor"] * (1 if antigo["sinal"] == "D" else -1))
    return True


# ---- regras de fornecedor ----

def excluir_regra_fornecedor(regra_id, organizacao_id):
    execute("DELETE FROM regras_fornecedor WHERE id = %s AND organizacao_id = %s", (regra_id, organizacao_id))


def fornecedores_sem_categoria(organizacao_id, limite=10):
    return query_all(
        "SELECT " + _FORN_SQL + " AS fornecedor, SUM(lc.valor) AS total, COUNT(*) AS n " + _BASE_LC +
        " AND lc.sinal = 'D' AND lc.categoria_id IS NULL GROUP BY " + _FORN_SQL + " ORDER BY total DESC LIMIT %s",
        (organizacao_id, limite),
    )


# ---- compras parceladas cadastradas à mão ----

def listar_compromissos(organizacao_id):
    return query_all(
        """SELECT k.*, p.nome AS pessoa_nome FROM compromissos_cartao k LEFT JOIN pessoas p ON p.id = k.pessoa_id
           WHERE k.organizacao_id = %s ORDER BY k.mes_inicial, k.id""",
        (organizacao_id,),
    )


def criar_compromisso(organizacao_id, descricao, valor_parcela, num_parcelas, mes_inicial, pessoa_id):
    execute(
        "INSERT INTO compromissos_cartao (organizacao_id, descricao, valor_parcela, num_parcelas, mes_inicial, pessoa_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (organizacao_id, descricao, valor_parcela, num_parcelas, mes_inicial, pessoa_id),
    )


def excluir_compromisso(compromisso_id, organizacao_id):
    execute("DELETE FROM compromissos_cartao WHERE id = %s AND organizacao_id = %s", (compromisso_id, organizacao_id))



# ---------- Planejamento mensal: gastos fixos e recorrentes ----------

def listar_gastos_fixos(organizacao_id):
    return query_all(
        """SELECT g.*, c.nome AS categoria_nome FROM gastos_fixos g LEFT JOIN categorias c ON c.id = g.categoria_id
           WHERE g.organizacao_id = %s ORDER BY g.ativo DESC, g.dia_mes, g.nome""",
        (organizacao_id,),
    )


def excluir_gasto_fixo(gasto_id, organizacao_id):
    execute("DELETE FROM gastos_fixos WHERE id = %s AND organizacao_id = %s", (gasto_id, organizacao_id))


def renda_planejada_por_mes(organizacao_id, mes_ini, mes_fim):
    """Soma das receitas planejadas (tela Planejamento) por mês, no intervalo."""
    linhas = query_all(
        """SELECT p.mes_referencia, SUM(p.valor_limite) AS total FROM planejamentos p
           JOIN categorias c ON c.id = p.categoria_id
           WHERE c.organizacao_id = %s AND c.tipo = 'receita' AND p.mes_referencia BETWEEN %s AND %s
           GROUP BY p.mes_referencia""",
        (organizacao_id, mes_ini, mes_fim),
    )
    return {r["mes_referencia"]: float(r["total"] or 0) for r in linhas}


# ---------- Assistente de IA ----------

def salvar_config_ia(organizacao_id, ativa, analise_automatica):
    execute("UPDATE organizacoes_preferencias SET ia_ativa = %s, ia_analise_automatica = %s WHERE organizacao_id = %s",
            (ativa, analise_automatica, organizacao_id))


def salvar_mensagem_ia(organizacao_id, usuario_id, tipo, texto, mes=None):
    execute("INSERT INTO ia_mensagens (organizacao_id, usuario_id, tipo, mes_referencia, texto) VALUES (%s, %s, %s, %s, %s)",
            (organizacao_id, usuario_id, tipo, mes, texto))


def listar_mensagens_ia(organizacao_id, usuario_id, limite=40):
    return query_all(
        """SELECT * FROM (SELECT * FROM ia_mensagens WHERE organizacao_id = %s AND usuario_id = %s
                          AND tipo IN ('pergunta', 'resposta') ORDER BY criado_em DESC, id DESC LIMIT %s) t
           ORDER BY criado_em, id""",
        (organizacao_id, usuario_id, limite),
    )


def ultima_analise_ia(organizacao_id, mes):
    return query_one(
        "SELECT * FROM ia_mensagens WHERE organizacao_id = %s AND tipo = 'analise' AND mes_referencia = %s "
        "ORDER BY criado_em DESC, id DESC LIMIT 1",
        (organizacao_id, mes),
    )


def contar_chamadas_ia(organizacao_id, horas=24):
    row = query_one(
        "SELECT COUNT(*) AS n FROM ia_mensagens WHERE organizacao_id = %s AND tipo IN ('pergunta', 'analise') "
        "AND criado_em > now() - (%s * interval '1 hour')",
        (organizacao_id, horas),
    )
    return int(row["n"]) if row else 0


def limpar_mensagens_ia(organizacao_id, usuario_id):
    execute("DELETE FROM ia_mensagens WHERE organizacao_id = %s AND usuario_id = %s AND tipo IN ('pergunta', 'resposta')",
            (organizacao_id, usuario_id))



# ---------- Base do cartão: conta, fatura pelo VENCIMENTO, lentes e integração com Início/Controle ----------
# O "mês" de uma fatura (faturas.mes_referencia) é o mês do VENCIMENTO: é quando o dinheiro sai.

_MES_FATURA = "f.mes_referencia"
# lente "data da compra": à vista conta no mês da compra; PARCELA fica sempre no mês da fatura
_MES_COMPRA = ("CASE WHEN COALESCE(lc.parcela_total, 0) > 1 THEN f.mes_referencia "
               "ELSE COALESCE(to_char(lc.data_iso, 'YYYY-MM'), f.mes_referencia) END")
_SEM_PASSAGEM = "COALESCE(lc.tipo, '') NOT IN ('SALDO_ANTERIOR', 'PAGAMENTO')"
# compra lançada à mão no cartão: quando a organização importa faturas, a fatura vale (evita contar duas vezes)
_CARTAO_MANUAL = ("l.tipo = 'despesa' AND starts_with(COALESCE(fp.nome, ''), 'Cartão de Crédito') AND EXISTS "
                  "(SELECT 1 FROM faturas f2 JOIN cartoes c2 ON c2.id = f2.cartao_id WHERE c2.organizacao_id = l.organizacao_id)")


def _mes_expr(lente):
    return _MES_COMPRA if lente == "compra" else _MES_FATURA


def listar_cartoes_do_banco(organizacao_id, banco):
    return query_all("SELECT * FROM cartoes WHERE organizacao_id = %s AND banco = %s ORDER BY id", (organizacao_id, banco))


def buscar_cartao(organizacao_id, cartao_id):
    return query_one("SELECT * FROM cartoes WHERE id = %s AND organizacao_id = %s", (cartao_id, organizacao_id))


def criar_cartao_conta(organizacao_id, banco, final, nome):
    return execute("INSERT INTO cartoes (organizacao_id, nome, banco, final_cartao, ativo) VALUES (%s, %s, %s, %s, true) RETURNING *",
                   (organizacao_id, nome, banco, final))


def ultima_fatura_do_cartao(organizacao_id, cartao_id):
    return query_one(
        """SELECT f.* FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %s AND c.id = %s ORDER BY f.mes_referencia DESC, f.id DESC LIMIT 1""",
        (organizacao_id, cartao_id))


def garantir_categoria(organizacao_id, nome, tipo="despesa"):
    """Devolve o id da categoria, criando-a se a organização ainda não tiver (ex.: 'Encargos financeiros')."""
    achada = buscar_categoria_por_nome(organizacao_id, nome)
    if achada:
        return achada["id"]
    return execute("INSERT INTO categorias (organizacao_id, nome, ordem, tipo) VALUES (%s, %s, 99, %s) RETURNING id",
                   (organizacao_id, nome, tipo))["id"]


def org_tem_faturas(organizacao_id):
    return bool(query_one("SELECT EXISTS (SELECT 1 FROM faturas f JOIN cartoes c ON c.id = f.cartao_id WHERE c.organizacao_id = %s) AS tem",
                          (organizacao_id,))["tem"])


def total_faturas_mes(organizacao_id, mes):
    """Quanto vence no cartão neste mês (soma das faturas do mês do vencimento)."""
    row = query_one(
        """SELECT COALESCE(SUM(f.valor_total), 0) AS total, COALESCE(bool_or(f.previa), false) AS previa, COUNT(*) AS n
           FROM faturas f JOIN cartoes c ON c.id = f.cartao_id WHERE c.organizacao_id = %s AND f.mes_referencia = %s""",
        (organizacao_id, mes))
    return {"total": float(row["total"]), "previa": bool(row["previa"]), "n": int(row["n"])}


def resumo_meses_cartao(organizacao_id, lente="fatura"):
    """Uma linha por mês (todos os cartões somados). lente 'fatura' = mês do vencimento; 'compra' = mês do consumo."""
    if lente == "compra":
        return query_all(
            "SELECT m.mes AS mes_referencia, SUM(m.v) AS total, NULL::date AS vencimento, NULL::numeric AS limite_disponivel, "
            "NULL::numeric AS limite_total, NULL::bigint AS n_cartoes, false AS previa FROM ("
            "SELECT " + _MES_COMPRA + " AS mes, CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END AS v " + _BASE_LC +
            ") m GROUP BY m.mes ORDER BY m.mes DESC", (organizacao_id,))
    return query_all(
        """SELECT f.mes_referencia, SUM(f.valor_total) AS total, MIN(f.vencimento) AS vencimento,
                  MAX(f.limite_disponivel) AS limite_disponivel, MAX(f.limite_total) AS limite_total,
                  COUNT(*) AS n_cartoes, COALESCE(bool_or(f.previa), false) AS previa
           FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %s GROUP BY f.mes_referencia ORDER BY f.mes_referencia DESC""",
        (organizacao_id,))


def faturas_do_mes(organizacao_id, mes):
    return query_all(
        """SELECT f.id, f.valor_total, f.vencimento, f.previa, c.nome AS cartao_nome,
                  (SELECT COUNT(*) FROM lancamentos_cartao lc WHERE lc.fatura_id = f.id) AS n_transacoes
           FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %s AND f.mes_referencia = %s ORDER BY f.valor_total DESC""",
        (organizacao_id, mes))


def titulares_do_mes(organizacao_id, mes, lente="fatura"):
    """Quem gastou no mês: uma linha por titular; as linhas sem titular (encargos, ajustes) vêm com pessoa_nome NULL."""
    return query_all(
        "SELECT p.id AS pessoa_id, p.nome AS pessoa_nome, "
        "SUM(CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END) AS total, COUNT(*) AS n "
        "FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id "
        "LEFT JOIN pessoas p ON p.id = lc.pessoa_id WHERE c.organizacao_id = %s AND " + _mes_expr(lente) + " = %s AND " + _SEM_PASSAGEM +
        " GROUP BY p.id, p.nome ORDER BY total DESC", (organizacao_id, mes))


def titulares_por_fatura(organizacao_id):
    return query_all(
        "SELECT lc.fatura_id, p.nome AS pessoa_nome, SUM(CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END) AS total, COUNT(*) AS n "
        "FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id "
        "LEFT JOIN pessoas p ON p.id = lc.pessoa_id WHERE c.organizacao_id = %s AND " + _SEM_PASSAGEM +
        " GROUP BY lc.fatura_id, p.nome ORDER BY lc.fatura_id, total DESC", (organizacao_id,))


def gastos_por_fornecedor_cartao(organizacao_id, mes, limite=8, lente="fatura"):
    return query_all(
        "SELECT " + _FORN_SQL + " AS fornecedor, SUM(lc.valor) AS total, COUNT(*) AS n " + _BASE_LC +
        " AND " + _mes_expr(lente) + " = %s AND lc.sinal = 'D' GROUP BY " + _FORN_SQL + " ORDER BY total DESC LIMIT %s",
        (organizacao_id, mes, limite))


def totais_mes(organizacao_id, mes_referencia):
    """Receitas, despesas e saldo do mês. O CARTÃO entra pelo mês do vencimento da fatura."""
    row = query_one(
        """SELECT COALESCE(SUM(CASE WHEN l.tipo = 'receita' THEN l.valor ELSE 0 END), 0) AS receitas,
                  COALESCE(SUM(CASE WHEN l.tipo = 'despesa' THEN l.valor ELSE 0 END), 0) AS despesas
           FROM lancamentos l LEFT JOIN formas_pagamento fp ON fp.id = l.forma_pagamento_id
           WHERE l.organizacao_id = %s AND to_char(l.data, 'YYYY-MM') = %s AND NOT (""" + _CARTAO_MANUAL + ")",
        (organizacao_id, mes_referencia))
    cartao = total_faturas_mes(organizacao_id, mes_referencia)
    receitas = float(row["receitas"])
    despesas = float(row["despesas"]) + cartao["total"]
    return {"receitas": receitas, "despesas": despesas, "saldo": receitas - despesas, "cartao": cartao["total"], "cartao_previa": cartao["previa"]}





# ---------- Módulo Pessoa + Empresa ----------

# Orçamento da FAMÍLIA = tudo que não é de uma empresa
_FAMILIA_L = "l.destino_empresa_id IS NULL"
_FAMILIA_LC = "lc.destino_empresa_id IS NULL"


def listar_empresas(organizacao_id, apenas_ativas=True):
    sql = "SELECT * FROM empresas WHERE organizacao_id = %s"
    if apenas_ativas:
        sql += " AND ativa = true"
    return query_all(sql + " ORDER BY nome", (organizacao_id,))


def buscar_empresa(organizacao_id, empresa_id):
    return query_one("SELECT * FROM empresas WHERE id = %s AND organizacao_id = %s", (empresa_id, organizacao_id))


def criar_empresa(organizacao_id, nome):
    return execute("INSERT INTO empresas (organizacao_id, nome) VALUES (%s, %s) RETURNING *", (organizacao_id, nome))


def atualizar_empresa(empresa_id, organizacao_id, nome, ativa):
    execute("UPDATE empresas SET nome = %s, ativa = %s WHERE id = %s AND organizacao_id = %s", (nome, ativa, empresa_id, organizacao_id))


def empresa_em_uso(empresa_id, organizacao_id):
    """Quantos registros apontam para a empresa (se > 0, não pode excluir: só desativar)."""
    row = query_one(
        """SELECT (SELECT COUNT(*) FROM lancamentos WHERE destino_empresa_id = %(e)s) + (SELECT COUNT(*) FROM lancamentos_cartao WHERE destino_empresa_id = %(e)s)
                + (SELECT COUNT(*) FROM gastos_fixos WHERE destino_empresa_id = %(e)s) + (SELECT COUNT(*) FROM regras_fornecedor WHERE destino_empresa_id = %(e)s)
                + (SELECT COUNT(*) FROM cartoes WHERE dono_empresa_id = %(e)s) + (SELECT COUNT(*) FROM contas_bancarias WHERE dono_empresa_id = %(e)s)
                + (SELECT COUNT(*) FROM acertos WHERE empresa_id = %(e)s) AS n""", {"e": empresa_id})
    return int(row["n"])


def excluir_empresa(empresa_id, organizacao_id):
    execute("DELETE FROM empresas WHERE id = %s AND organizacao_id = %s", (empresa_id, organizacao_id))


def salvar_modulo_empresa(organizacao_id, ativo):
    execute("UPDATE organizacoes_preferencias SET modulo_empresa = %s WHERE organizacao_id = %s", (bool(ativo), organizacao_id))


# ---- acertos ----

def listar_acertos(organizacao_id, empresa_id=None):
    sql, params = "SELECT * FROM acertos WHERE organizacao_id = %s", [organizacao_id]
    if empresa_id:
        sql += " AND empresa_id = %s"; params.append(empresa_id)
    return query_all(sql + " ORDER BY data DESC, id DESC", params)


def criar_acerto(organizacao_id, empresa_id, data, valor, sentido, descricao):
    execute("INSERT INTO acertos (organizacao_id, empresa_id, data, valor, sentido, descricao) VALUES (%s, %s, %s, %s, %s, %s)",
            (organizacao_id, empresa_id, data, valor, sentido, descricao))


def excluir_acerto(acerto_id, organizacao_id):
    execute("DELETE FROM acertos WHERE id = %s AND organizacao_id = %s", (acerto_id, organizacao_id))


def acerto_itens(organizacao_id):
    """Pendências brutas: onde QUEM PAGOU (dono do cartão/conta) é diferente de PARA QUEM foi o gasto."""
    return query_all(
        """SELECT 'cartao' AS origem, lc.id, f.mes_referencia AS mes, lc.data_iso AS data,
                  COALESCE(NULLIF(TRIM(lc.fornecedor), ''), lc.descricao) AS descricao,
                  CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END AS valor,
                  c.dono_empresa_id AS pagador, lc.destino_empresa_id AS destino
           FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %(org)s AND COALESCE(lc.tipo, '') NOT IN ('SALDO_ANTERIOR', 'PAGAMENTO')
             AND c.dono_empresa_id IS DISTINCT FROM lc.destino_empresa_id
           UNION ALL
           SELECT 'manual', l.id, to_char(l.data, 'YYYY-MM'), l.data, COALESCE(l.descricao, ''), l.valor,
                  CASE WHEN l.cartao_id IS NOT NULL THEN ca.dono_empresa_id WHEN l.conta_bancaria_id IS NOT NULL THEN cb.dono_empresa_id ELSE NULL END,
                  l.destino_empresa_id
           FROM lancamentos l LEFT JOIN formas_pagamento fp ON fp.id = l.forma_pagamento_id
                LEFT JOIN cartoes ca ON ca.id = l.cartao_id LEFT JOIN contas_bancarias cb ON cb.id = l.conta_bancaria_id
           WHERE l.organizacao_id = %(org)s AND NOT (""" + _CARTAO_MANUAL + """)
             AND l.tipo = 'despesa'
             AND (CASE WHEN l.cartao_id IS NOT NULL THEN ca.dono_empresa_id WHEN l.conta_bancaria_id IS NOT NULL THEN cb.dono_empresa_id ELSE NULL END)
                 IS DISTINCT FROM l.destino_empresa_id""",
        {"org": organizacao_id})


# ---- análise com o destino ----

def realizado_por_categoria_mes(organizacao_id, mes_referencia, incluir_sem_categoria=False):
    """Controle = orçamento da FAMÍLIA: o que é de uma empresa fica de fora.
    Os créditos da fatura (estornos) abatem a categoria deles, então a soma do cartão fecha com o total da fatura.
    Com incluir_sem_categoria, o gasto sem categoria vem na chave None."""
    rows = query_all(
        """SELECT categoria_id, SUM(valor) AS total FROM (
             SELECT l.categoria_id, l.valor FROM lancamentos l LEFT JOIN formas_pagamento fp ON fp.id = l.forma_pagamento_id
               WHERE l.organizacao_id = %(org)s AND l.tipo = 'despesa' AND to_char(l.data, 'YYYY-MM') = %(mes)s AND NOT (""" + _CARTAO_MANUAL + """)
                 AND """ + _FAMILIA_L + """
             UNION ALL
             SELECT lc.categoria_id, CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END AS valor FROM lancamentos_cartao lc
               JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id
               WHERE c.organizacao_id = %(org)s AND f.mes_referencia = %(mes)s AND """ + _SEM_PASSAGEM + """
                 AND """ + _FAMILIA_LC + """
           ) t GROUP BY categoria_id""",
        {"org": organizacao_id, "mes": mes_referencia})
    return {r["categoria_id"]: float(r["total"]) for r in rows if incluir_sem_categoria or r["categoria_id"] is not None}


def gastos_por_categoria_cartao(organizacao_id, mes, lente="fatura", so_familia=False):
    return query_all(
        "SELECT cat.id AS categoria_id, COALESCE(cat.nome, 'Sem categoria') AS categoria, SUM(lc.valor) AS total, COUNT(*) AS n " + _BASE_LC +
        " AND " + _mes_expr(lente) + " = %s AND lc.sinal = 'D'" + (" AND " + _FAMILIA_LC if so_familia else "") +
        " GROUP BY cat.id, cat.nome ORDER BY total DESC", (organizacao_id, mes))


def creditos_cartao_mes(organizacao_id, mes, lente="fatura", so_familia=False):
    row = query_one("SELECT COALESCE(SUM(lc.valor), 0) AS total " + _BASE_LC + " AND " + _mes_expr(lente) + " = %s AND lc.sinal = 'C'" +
                    (" AND " + _FAMILIA_LC if so_familia else ""), (organizacao_id, mes))
    return float(row["total"]) if row else 0.0


def destinos_do_mes(organizacao_id, mes, lente="fatura"):
    """Para quem foi o cartão no mês: empresa_id vazio = Família."""
    return query_all(
        "SELECT e.id AS empresa_id, e.nome AS empresa_nome, SUM(CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END) AS total, COUNT(*) AS n "
        "FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id JOIN cartoes c ON c.id = f.cartao_id "
        "LEFT JOIN empresas e ON e.id = lc.destino_empresa_id WHERE c.organizacao_id = %s AND " + _mes_expr(lente) + " = %s AND " + _SEM_PASSAGEM +
        " GROUP BY e.id, e.nome ORDER BY total DESC", (organizacao_id, mes))


def total_empresa_cartao_mes(organizacao_id, mes):
    row = query_one(
        "SELECT COALESCE(SUM(CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END), 0) AS total " + _BASE_LC +
        " AND f.mes_referencia = %s AND lc.destino_empresa_id IS NOT NULL", (organizacao_id, mes))
    return float(row["total"])


def empresa_cartao_por_mes(organizacao_id):
    rows = query_all(
        "SELECT f.mes_referencia AS mes, SUM(CASE WHEN lc.sinal = 'D' THEN lc.valor ELSE -lc.valor END) AS total " + _BASE_LC +
        " AND lc.destino_empresa_id IS NOT NULL GROUP BY f.mes_referencia", (organizacao_id,))
    return {r["mes"]: float(r["total"]) for r in rows}


def compras_parceladas_cartao(organizacao_id):
    return query_all(
        """SELECT lc.id, COALESCE(NULLIF(TRIM(lc.fornecedor), ''), lc.descricao) AS descricao, lc.nao_projetar,
                  lc.valor, lc.parcela_atual, lc.parcela_total, lc.pessoa_id, lc.destino_empresa_id,
                  f.mes_referencia, p.nome AS pessoa_nome
           FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id
                JOIN cartoes c ON c.id = f.cartao_id LEFT JOIN pessoas p ON p.id = lc.pessoa_id
           WHERE c.organizacao_id = %s AND lc.sinal = 'D' AND lc.parcela_total > 1 AND lc.parcela_atual IS NOT NULL""",
        (organizacao_id,))


# ---- regras de fornecedor (agora com destino) ----

def listar_regras_fornecedor(organizacao_id):
    return query_all(
        """SELECT r.*, c.nome AS categoria_nome, e.nome AS destino_nome FROM regras_fornecedor r
           LEFT JOIN categorias c ON c.id = r.categoria_id LEFT JOIN empresas e ON e.id = r.destino_empresa_id
           WHERE r.organizacao_id = %s ORDER BY LENGTH(r.padrao) DESC, r.nome""",
        (organizacao_id,))


def criar_regra_fornecedor(organizacao_id, padrao, nome, categoria_id, define_destino=False, destino_empresa_id=None):
    return execute(
        """INSERT INTO regras_fornecedor (organizacao_id, padrao, nome, categoria_id, define_destino, destino_empresa_id)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (organizacao_id, padrao) DO UPDATE SET nome = EXCLUDED.nome, categoria_id = EXCLUDED.categoria_id,
                define_destino = EXCLUDED.define_destino, destino_empresa_id = EXCLUDED.destino_empresa_id
           RETURNING *""",
        (organizacao_id, padrao, nome, categoria_id, define_destino, destino_empresa_id))


def atualizar_regra_fornecedor(regra_id, organizacao_id, padrao, nome, categoria_id, define_destino=False, destino_empresa_id=None):
    execute("UPDATE regras_fornecedor SET padrao = %s, nome = %s, categoria_id = %s, define_destino = %s, destino_empresa_id = %s "
            "WHERE id = %s AND organizacao_id = %s",
            (padrao, nome, categoria_id, define_destino, destino_empresa_id, regra_id, organizacao_id))


def aplicar_regra_fornecedor(organizacao_id, padrao, nome, categoria_id, define_destino=False, destino_empresa_id=None):
    """Aplica a regra nas compras JÁ importadas (busca por trecho do texto, sem diferenciar maiúsculas).
    Devolve quantas compras foram ajustadas."""
    n = query_one(
        """SELECT COUNT(*) AS n FROM lancamentos_cartao lc JOIN faturas f ON f.id = lc.fatura_id
           JOIN cartoes c ON c.id = f.cartao_id
           WHERE c.organizacao_id = %s AND POSITION(%s IN UPPER(lc.descricao)) > 0""",
        (organizacao_id, padrao))["n"]
    execute(
        """UPDATE lancamentos_cartao lc SET fornecedor = %s, categoria_id = COALESCE(%s, lc.categoria_id),
                  destino_empresa_id = CASE WHEN %s THEN %s ELSE lc.destino_empresa_id END
           FROM faturas f JOIN cartoes c ON c.id = f.cartao_id
           WHERE lc.fatura_id = f.id AND c.organizacao_id = %s AND POSITION(%s IN UPPER(lc.descricao)) > 0""",
        (nome, categoria_id, bool(define_destino), destino_empresa_id, organizacao_id, padrao))
    return int(n)


# ---- gastos fixos (agora com destino) ----

def criar_gasto_fixo(organizacao_id, d):
    execute(
        """INSERT INTO gastos_fixos (organizacao_id, nome, valor, estimado, dia_mes, frequencia, mes_inicio, mes_fim, no_cartao, categoria_id,
                  destino_empresa_id, fornecedor, observacao, ativo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (organizacao_id, d["nome"], d["valor"], d["estimado"], d["dia_mes"], d["frequencia"], d["mes_inicio"],
         d["mes_fim"], d["no_cartao"], d["categoria_id"], d.get("destino_empresa_id"), d.get("fornecedor"), d.get("observacao"), d.get("ativo", True)))


def atualizar_gasto_fixo(gasto_id, organizacao_id, d):
    execute(
        """UPDATE gastos_fixos SET nome=%s, valor=%s, estimado=%s, dia_mes=%s, frequencia=%s, mes_inicio=%s,
                  mes_fim=%s, no_cartao=%s, categoria_id=%s, ativo=%s, destino_empresa_id=%s, fornecedor=%s, observacao=%s
           WHERE id=%s AND organizacao_id=%s""",
        (d["nome"], d["valor"], d["estimado"], d["dia_mes"], d["frequencia"], d["mes_inicio"], d["mes_fim"],
         d["no_cartao"], d["categoria_id"], d["ativo"], d.get("destino_empresa_id"), d.get("fornecedor"), d.get("observacao"), gasto_id, organizacao_id))


def modulo_empresa_ativo(organizacao_id):
    prefs = buscar_preferencias(organizacao_id)
    return bool(prefs and prefs.get("modulo_empresa"))


def empresas_ids(organizacao_id):
    """Ids das empresas da organização com o módulo ligado; sem o módulo, vazio (tudo é Família)."""
    if not modulo_empresa_ativo(organizacao_id):
        return set()
    return {e["id"] for e in listar_empresas(organizacao_id, apenas_ativas=False)}


def valores_cartao_mes(organizacao_id, mes):
    """Valores das compras do cartão na fatura do mês (para conferir a planilha com a fatura importada)."""
    rows = query_all(
        "SELECT lc.valor " + _BASE_LC + " AND f.mes_referencia = %s AND lc.sinal = 'D' AND " + _SEM_PASSAGEM, (organizacao_id, mes))
    return [float(r["valor"]) for r in rows]
