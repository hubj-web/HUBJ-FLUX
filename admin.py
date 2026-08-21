# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import email_service
from auth import login_required, requer_papel

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/organizacoes")
@login_required
@requer_papel("super_admin")
def listar_organizacoes():
    organizacoes = db.query_all(
        """SELECT o.*,
                  (SELECT COUNT(*) FROM usuarios u WHERE u.organizacao_id = o.id AND u.status != 'bloqueado') AS usuarios_atuais
           FROM organizacoes o ORDER BY o.criado_em DESC"""
    )
    for org in organizacoes:
        org["usuarios"] = db.listar_usuarios_por_organizacao(org["id"])
    return render_template("organizacoes.html", organizacoes=organizacoes)


@admin_bp.route("/organizacoes/nova", methods=["POST"])
@login_required
@requer_papel("super_admin")
def criar_organizacao():
    nome = request.form.get("nome", "").strip()
    tipo = request.form.get("tipo")
    limite_usuarios = int(request.form.get("limite_usuarios") or 1)
    email_admin = request.form.get("email_admin", "").strip().lower()

    if not nome or tipo not in ("familia", "empresa") or not email_admin:
        flash("Preencha nome, tipo e e-mail do administrador.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))

    if db.buscar_usuario_por_email(email_admin):
        flash(f"O e-mail {email_admin} já está cadastrado no sistema "
              f"(cada e-mail só pode pertencer a um usuário). Use outro e-mail.", "erro")
        return redirect(url_for("admin.listar_organizacoes"))

    org = db.execute(
        """INSERT INTO organizacoes (nome, tipo, limite_usuarios, criado_por, criado_em)
           VALUES (%s, %s, %s, %s, now()) RETURNING *""",
        (nome, tipo, limite_usuarios, g.usuario_atual["id"]),
    )
    db.execute("INSERT INTO organizacoes_preferencias (organizacao_id) VALUES (%s)", (org["id"],))
    db.seed_organizacao(org["id"])

    db.execute(
        """INSERT INTO usuarios (organizacao_id, email, papel, status, convidado_por, criado_em)
           VALUES (%s, %s, 'admin_cliente', 'pendente', %s, now())""",
        (org["id"], email_admin, g.usuario_atual["id"]),
    )

    if email_service.enviar_convite_admin_cliente(email_admin, nome):
        flash(f"Organização \"{nome}\" criada. E-mail de convite enviado para {email_admin}.", "ok")
    else:
        flash(f"Organização \"{nome}\" criada. {email_admin} já pode fazer login com o Google "
              f"(e-mail automático não configurado — avise a pessoa manualmente).", "ok")
    return redirect(url_for("admin.listar_organizacoes"))


@admin_bp.route("/organizacoes/<int:org_id>/limite", methods=["POST"])
@login_required
@requer_papel("super_admin")
def ajustar_limite(org_id):
    novo_limite = int(request.form.get("limite_usuarios") or 1)
    db.execute("UPDATE organizacoes SET limite_usuarios = %s WHERE id = %s", (novo_limite, org_id))
    flash("Limite de usuários atualizado.", "ok")
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
    db.execute("DELETE FROM organizacoes WHERE id = %s", (org_id,))
    flash(f"Organização \"{org['nome']}\" e todos os dados associados foram excluídos definitivamente.", "ok")
    return redirect(url_for("admin.listar_organizacoes"))
