# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import email_service
from validacao import email_valido
from auth import login_required, requer_papel

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/organizacoes")
@login_required
@requer_papel("super_admin")
def listar_organizacoes():
    organizacoes = db.query_all(
        """SELECT o.*, c.nome AS cliente_nome FROM organizacoes o LEFT JOIN clientes c ON c.id = o.cliente_id
           ORDER BY COALESCE(o.cliente_id, o.id) DESC, (o.tipo = 'familia') DESC, o.criado_em"""
    )
    for org in organizacoes:
        org["usuarios_atuais"] = db.contar_usuarios_ativos(org["id"])
        org["usuarios"] = db.listar_usuarios_por_organizacao(org["id"])
        prefs = db.buscar_preferencias(org["id"])
        org["modulo_empresa"] = bool(prefs and prefs.get("modulo_empresa"))
    clientes = db.query_all("SELECT id, nome FROM clientes ORDER BY nome")
    modelos = [(chave, m["nome"]) for chave, m in db.MODELOS_EMPRESA.items()]
    return render_template("organizacoes.html", organizacoes=organizacoes, clientes=clientes, modelos=modelos)


@admin_bp.route("/organizacoes/nova", methods=["POST"])
@login_required
@requer_papel("super_admin")
def criar_organizacao():
    nome = request.form.get("nome", "").strip()
    tipo = request.form.get("tipo")
    try:
        limite_usuarios = int(request.form.get("limite_usuarios") or 1)
    except ValueError:
        limite_usuarios = 0
    email_admin = request.form.get("email_admin", "").strip().lower()

    if not nome or tipo not in ("familia", "empresa") or not 1 <= limite_usuarios <= 100:
        flash("Preencha o nome, o tipo e um limite de usuários entre 1 e 100.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))
    if not email_valido(email_admin):
        flash("Informe um e-mail válido para o administrador (por exemplo, nome@exemplo.com).", "erro")
        return redirect(url_for("admin.listar_organizacoes"))

    if db.buscar_usuario_por_email(email_admin):
        flash(f"O e-mail {email_admin} já está cadastrado no sistema "
              f"(cada e-mail só pode pertencer a um usuário). Use outro e-mail.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))

    cliente = db.criar_cliente(nome)
    org = db.execute(
        """INSERT INTO organizacoes (nome, tipo, limite_usuarios, criado_por, criado_em, cliente_id)
           VALUES (%s, %s, %s, %s, now(), %s) RETURNING *""",
        (nome, tipo, limite_usuarios, g.usuario_atual["id"], cliente["id"]),
    )
    db.execute("INSERT INTO organizacoes_preferencias (organizacao_id) VALUES (%s)", (org["id"],))
    db.seed_organizacao(org["id"], tipo, db.modelo_empresa_valido(request.form.get("modelo")))  # o modelo só vale para empresa
    db.convidar_usuario_organizacao(org["id"], email_admin, "admin_cliente", g.usuario_atual["id"])

    if email_service.enviar_convite_admin_cliente(email_admin, nome):
        flash(f"Cliente \"{nome}\" criado. E-mail de convite enviado para {email_admin}.", "ok")
    else:
        flash(f"Cliente \"{nome}\" criado. {email_admin} já pode fazer login com o Google "
              f"(e-mail automático não configurado — avise a pessoa manualmente).", "ok")
    return redirect(url_for("admin.listar_organizacoes"))


@admin_bp.route("/clientes/espaco-empresa", methods=["POST"])
@login_required
@requer_papel("super_admin")
def criar_espaco_empresa():
    """Acrescenta um espaço de Empresa a um cliente que já existe. Quem administra o cliente já ganha acesso a ele."""
    nome = request.form.get("nome", "").strip()
    try:
        cliente_id = int(request.form.get("cliente_id") or 0)
        limite_usuarios = int(request.form.get("limite_usuarios") or 1)
    except ValueError:
        cliente_id, limite_usuarios = 0, 0
    cliente = db.query_one("SELECT id, nome FROM clientes WHERE id = %s", (cliente_id,)) if cliente_id else None
    if cliente is None or not nome or not 1 <= limite_usuarios <= 100:
        flash("Escolha o cliente, digite o nome da empresa e um limite de usuários entre 1 e 100.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))
    if not db.query_one("""SELECT 1 AS ok FROM acessos a JOIN organizacoes o ON o.id = a.organizacao_id
                           WHERE o.cliente_id = %s AND a.papel = 'admin_cliente' LIMIT 1""", (cliente["id"],)):
        flash("Este cliente ainda não tem um administrador. Convide um antes de criar a empresa.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))
    org, n_donos = db.criar_espaco_empresa(cliente["id"], nome, limite_usuarios, g.usuario_atual["id"], db.modelo_empresa_valido(request.form.get("modelo")))
    flash(f"Espaço de empresa \"{nome}\" criado para {cliente['nome']}. {n_donos} administrador(es) do cliente já podem alternar para ele.", "ok")
    return redirect(url_for("admin.listar_organizacoes"))


@admin_bp.route("/organizacoes/<int:org_id>/limite", methods=["POST"])
@login_required
@requer_papel("super_admin")
def ajustar_limite(org_id):
    novo_limite = int(request.form.get("limite_usuarios") or 1)
    db.execute("UPDATE organizacoes SET limite_usuarios = %s WHERE id = %s", (novo_limite, org_id))
    flash("Limite de usuários atualizado.", "ok")
    return redirect(url_for("admin.listar_organizacoes"))


@admin_bp.route("/organizacoes/<int:org_id>/modulo-empresa", methods=["POST"])
@login_required
@requer_papel("super_admin")
def alternar_modulo_empresa(org_id):
    prefs = db.buscar_preferencias(org_id)
    if prefs is None:
        flash("Organização não encontrada.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))
    novo = not bool(prefs.get("modulo_empresa"))
    db.salvar_modulo_empresa(org_id, novo)
    flash("Módulo Pessoa + Empresa " + ("ligado" if novo else "desligado") + " para esta organização.", "ok")
    return redirect(url_for("admin.listar_organizacoes"))


@admin_bp.route("/organizacoes/<int:org_id>/status", methods=["POST"])
@login_required
@requer_papel("super_admin")
def alternar_status(org_id):
    org = db.query_one("SELECT status FROM organizacoes WHERE id = %s", (org_id,))
    novo_status = "suspenso" if org["status"] == "ativo" else "ativo"
    db.execute("UPDATE organizacoes SET status = %s WHERE id = %s", (novo_status, org_id))
    flash(f"Organização marcada como {novo_status}.", "ok")
    return redirect(url_for("admin.listar_organizacoes"))


@admin_bp.route("/organizacoes/<int:org_id>/excluir", methods=["POST"])
@login_required
@requer_papel("super_admin")
def excluir_organizacao(org_id):
    org = db.query_one("SELECT nome FROM organizacoes WHERE id = %s", (org_id,))
    if org is None:
        flash("Organização não encontrada.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))
    db.preparar_exclusao_espaco(org_id)  # quem tinha este espaço como principal e tem outro não perde a conta
    db.execute("DELETE FROM organizacoes WHERE id = %s", (org_id,))
    db.execute("DELETE FROM clientes c WHERE NOT EXISTS (SELECT 1 FROM organizacoes o WHERE o.cliente_id = c.id)")  # cliente sem nenhum espaço some
    flash(f"Organização \"{org['nome']}\" e todos os dados associados foram excluídos definitivamente.", "ok")
    return redirect(url_for("admin.listar_organizacoes"))
