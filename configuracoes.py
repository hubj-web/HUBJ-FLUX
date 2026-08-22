# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import email_service
from auth import login_required, requer_organizacao, requer_papel

config_bp = Blueprint("config", __name__, url_prefix="/configuracoes")


@config_bp.route("/")
@login_required
@requer_organizacao
def index():
    return render_template("configuracoes.html")


# ---------- Categorias ----------

@config_bp.route("/categorias")
@login_required
@requer_organizacao
def categorias():
    org_id = g.usuario_atual["organizacao_id"]
    return render_template("config_categorias.html", categorias=db.listar_categorias_todas(org_id))


@config_bp.route("/categorias/nova", methods=["POST"])
@login_required
@requer_organizacao
def nova_categoria():
    org_id = g.usuario_atual["organizacao_id"]
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()
    tipo = request.form.get("tipo", "despesa")
    palavras_chave = request.form.get("palavras_chave", "").strip() or None
    if not nome:
        flash("Informe o nome da categoria.", "erro")
        return redirect(url_for("config.categorias"))
    db.criar_categoria(org_id, nome, descricao, tipo, palavras_chave)
    flash(f"Categoria \"{nome}\" criada.", "ok")
    return redirect(url_for("config.categorias"))


@config_bp.route("/categorias/<int:cat_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_categoria(cat_id):
    org_id = g.usuario_atual["organizacao_id"]
    db.atualizar_categoria(
        cat_id, org_id, request.form.get("nome", "").strip(), request.form.get("descricao", "").strip(),
        request.form.get("tipo", "despesa"), request.form.get("palavras_chave", "").strip() or None,
        request.form.get("ativa") == "on",
    )
    flash("Categoria atualizada.", "ok")
    return redirect(url_for("config.categorias"))


@config_bp.route("/categorias/<int:cat_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_categoria(cat_id):
    org_id = g.usuario_atual["organizacao_id"]
    try:
        db.excluir_categoria(cat_id, org_id)
        flash("Categoria excluída.", "ok")
    except Exception:
        flash("Não foi possível excluir - essa categoria já tem lançamentos associados. "
              "Use \"desativar\" em vez de excluir.", "erro")
    return redirect(url_for("config.categorias"))


# ---------- Formas de pagamento ----------

@config_bp.route("/formas-pagamento")
@login_required
@requer_organizacao
def formas_pagamento():
    org_id = g.usuario_atual["organizacao_id"]
    return render_template("config_formas_pagamento.html", formas=db.listar_formas_pagamento_todas(org_id))


@config_bp.route("/formas-pagamento/nova", methods=["POST"])
@login_required
@requer_organizacao
def nova_forma_pagamento():
    org_id = g.usuario_atual["organizacao_id"]
    nome = request.form.get("nome", "").strip()
    aplica_a = request.form.get("aplica_a", "ambos")
    permite_parcelamento = request.form.get("permite_parcelamento") == "on"
    if not nome:
        flash("Informe o nome da forma de pagamento.", "erro")
        return redirect(url_for("config.formas_pagamento"))
    db.criar_forma_pagamento(org_id, nome, aplica_a, permite_parcelamento)
    flash(f"Forma de pagamento \"{nome}\" criada.", "ok")
    return redirect(url_for("config.formas_pagamento"))


@config_bp.route("/formas-pagamento/<int:fp_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_forma_pagamento(fp_id):
    org_id = g.usuario_atual["organizacao_id"]
    db.atualizar_forma_pagamento(
        fp_id, org_id, request.form.get("nome", "").strip(), request.form.get("aplica_a", "ambos"),
        request.form.get("permite_parcelamento") == "on", request.form.get("ativa") == "on",
    )
    flash("Forma de pagamento atualizada.", "ok")
    return redirect(url_for("config.formas_pagamento"))


@config_bp.route("/formas-pagamento/<int:fp_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_forma_pagamento(fp_id):
    org_id = g.usuario_atual["organizacao_id"]
    try:
        db.excluir_forma_pagamento(fp_id, org_id)
        flash("Forma de pagamento excluída.", "ok")
    except Exception:
        flash("Não foi possível excluir - já tem lançamentos associados. Use \"desativar\".", "erro")
    return redirect(url_for("config.formas_pagamento"))


# ---------- Cartões ----------

# ---------- Contas Bancárias ----------

@config_bp.route("/contas")
@login_required
@requer_organizacao
def contas():
    org_id = g.usuario_atual["organizacao_id"]
    contas = db.listar_contas_bancarias(org_id, apenas_ativas=False)
    for c in contas:
        c["saldo_atual"] = db.saldo_atual_conta(c["id"], org_id)
    return render_template("config_contas.html", contas=contas)


@config_bp.route("/contas/nova", methods=["POST"])
@login_required
@requer_organizacao
def nova_conta():
    org_id = g.usuario_atual["organizacao_id"]
    nome = request.form.get("nome", "").strip()
    tipo = request.form.get("tipo", "corrente")
    saldo_inicial_str = (request.form.get("saldo_inicial") or "0").replace(".", "").replace(",", ".")
    if not nome:
        flash("Informe o nome da conta.", "erro")
        return redirect(url_for("config.contas"))
    try:
        saldo_inicial = float(saldo_inicial_str)
    except ValueError:
        saldo_inicial = 0
    db.criar_conta_bancaria(org_id, nome, tipo, saldo_inicial)
    flash(f"Conta \"{nome}\" criada.", "ok")
    return redirect(url_for("config.contas"))


@config_bp.route("/contas/<int:conta_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_conta(conta_id):
    org_id = g.usuario_atual["organizacao_id"]
    saldo_inicial_str = (request.form.get("saldo_inicial") or "0").replace(".", "").replace(",", ".")
    try:
        saldo_inicial = float(saldo_inicial_str)
    except ValueError:
        saldo_inicial = 0
    db.atualizar_conta_bancaria(
        conta_id, org_id, request.form.get("nome", "").strip(), request.form.get("tipo", "corrente"),
        saldo_inicial, request.form.get("ativa") == "on",
    )
    flash("Conta atualizada.", "ok")
    return redirect(url_for("config.contas"))


@config_bp.route("/contas/<int:conta_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_conta(conta_id):
    org_id = g.usuario_atual["organizacao_id"]
    try:
        db.excluir_conta_bancaria(conta_id, org_id)
        flash("Conta excluída.", "ok")
    except Exception:
        flash("Não foi possível excluir - essa conta já tem lançamentos associados. Use \"desativar\".", "erro")
    return redirect(url_for("config.contas"))


@config_bp.route("/cartoes")
@login_required
@requer_organizacao
def cartoes():
    org_id = g.usuario_atual["organizacao_id"]
    return render_template("config_cartoes.html", cartoes=db.listar_cartoes_todos(org_id),
                            pessoas=db.listar_pessoas_todas(org_id))


@config_bp.route("/cartoes/novo", methods=["POST"])
@login_required
@requer_organizacao
def novo_cartao():
    org_id = g.usuario_atual["organizacao_id"]
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome do cartão.", "erro")
        return redirect(url_for("config.cartoes"))
    db.criar_cartao_manual(
        org_id, nome, request.form.get("limite_total") or None,
        request.form.get("dia_fechamento") or None, request.form.get("dia_vencimento") or None,
        request.form.get("pessoa_id") or None,
    )
    flash(f"Cartão \"{nome}\" criado.", "ok")
    return redirect(url_for("config.cartoes"))


@config_bp.route("/cartoes/<int:cartao_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_cartao(cartao_id):
    org_id = g.usuario_atual["organizacao_id"]
    db.atualizar_cartao(
        cartao_id, org_id, request.form.get("nome", "").strip(), request.form.get("limite_total") or None,
        request.form.get("dia_fechamento") or None, request.form.get("dia_vencimento") or None,
        request.form.get("ativo") == "on", request.form.get("pessoa_id") or None,
    )
    flash("Cartão atualizado.", "ok")
    return redirect(url_for("config.cartoes"))


@config_bp.route("/cartoes/<int:cartao_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_cartao(cartao_id):
    org_id = g.usuario_atual["organizacao_id"]
    try:
        db.excluir_cartao(cartao_id, org_id)
        flash("Cartão excluído.", "ok")
    except Exception:
        flash("Não foi possível excluir - esse cartão já tem faturas importadas. Use \"desativar\".", "erro")
    return redirect(url_for("config.cartoes"))


# ---------- Pessoas ----------

@config_bp.route("/pessoas")
@login_required
@requer_organizacao
def pessoas():
    org_id = g.usuario_atual["organizacao_id"]
    return render_template("config_pessoas.html", pessoas=db.listar_pessoas_todas(org_id),
                            usuarios=db.listar_usuarios_por_organizacao(org_id))


@config_bp.route("/pessoas/nova", methods=["POST"])
@login_required
@requer_organizacao
def nova_pessoa():
    org_id = g.usuario_atual["organizacao_id"]
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome da pessoa.", "erro")
        return redirect(url_for("config.pessoas"))
    db.criar_pessoa_manual(org_id, nome, request.form.get("usuario_id") or None)
    flash(f"Pessoa \"{nome}\" cadastrada - já aparece no seletor de Lançamento.", "ok")
    return redirect(url_for("config.pessoas"))


@config_bp.route("/pessoas/<int:pessoa_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_pessoa(pessoa_id):
    org_id = g.usuario_atual["organizacao_id"]
    db.atualizar_pessoa(
        pessoa_id, org_id, request.form.get("nome", "").strip(),
        request.form.get("usuario_id") or None, request.form.get("disponivel_lancamento") == "on",
    )
    flash("Pessoa atualizada.", "ok")
    return redirect(url_for("config.pessoas"))


@config_bp.route("/pessoas/<int:pessoa_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_pessoa(pessoa_id):
    org_id = g.usuario_atual["organizacao_id"]
    try:
        db.excluir_pessoa(pessoa_id, org_id)
        flash("Pessoa excluída.", "ok")
    except Exception:
        flash("Não foi possível excluir - essa pessoa já tem lançamentos associados.", "erro")
    return redirect(url_for("config.pessoas"))


# ---------- Usuários da organização ----------

@config_bp.route("/usuarios")
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def usuarios():
    org_id = g.usuario_atual["organizacao_id"]
    organizacao = db.buscar_organizacao(org_id)
    return render_template("config_usuarios.html",
                            usuarios=db.listar_usuarios_por_organizacao(org_id), organizacao=organizacao)


@config_bp.route("/usuarios/convidar", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def convidar_usuario():
    org_id = g.usuario_atual["organizacao_id"]
    organizacao = db.buscar_organizacao(org_id)
    atuais = db.contar_usuarios_ativos(org_id)
    if atuais >= organizacao["limite_usuarios"]:
        flash(f"Limite de {organizacao['limite_usuarios']} usuário(s) atingido para esta organização. "
              f"Fale com o Super Admin para aumentar.", "erro")
        return redirect(url_for("config.usuarios"))

    email = request.form.get("email", "").strip().lower()
    papel = request.form.get("papel", "membro")
    if not email:
        flash("Informe o e-mail.", "erro")
        return redirect(url_for("config.usuarios"))
    if db.buscar_usuario_por_email(email):
        flash(f"O e-mail {email} já está cadastrado no sistema.", "erro")
        return redirect(url_for("config.usuarios"))

    db.convidar_usuario_organizacao(org_id, email, papel, g.usuario_atual["id"])
    if email_service.enviar_convite_membro(email, organizacao["nome"]):
        flash(f"Convite enviado para {email}.", "ok")
    else:
        flash(f"{email} já pode fazer login com o Google (e-mail automático não configurado).", "ok")
    return redirect(url_for("config.usuarios"))


@config_bp.route("/usuarios/<int:usuario_id>/remover", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def remover_usuario(usuario_id):
    org_id = g.usuario_atual["organizacao_id"]
    if usuario_id == g.usuario_atual["id"]:
        flash("Você não pode remover a si mesmo.", "erro")
        return redirect(url_for("config.usuarios"))
    db.remover_usuario_organizacao(usuario_id, org_id)
    flash("Usuário removido.", "ok")
    return redirect(url_for("config.usuarios"))


@config_bp.route("/usuarios/<int:usuario_id>/bloquear", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def bloquear_usuario(usuario_id):
    org_id = g.usuario_atual["organizacao_id"]
    if usuario_id == g.usuario_atual["id"]:
        flash("Você não pode desativar a si mesmo.", "erro")
        return redirect(url_for("config.usuarios"))
    db.bloquear_usuario_organizacao(usuario_id, org_id)
    flash("Usuário desativado - o acesso dele fica bloqueado até você reativar.", "ok")
    return redirect(url_for("config.usuarios"))


@config_bp.route("/usuarios/<int:usuario_id>/reativar", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def reativar_usuario(usuario_id):
    org_id = g.usuario_atual["organizacao_id"]
    db.reativar_usuario_organizacao(usuario_id, org_id)
    flash("Usuário reativado.", "ok")
    return redirect(url_for("config.usuarios"))
