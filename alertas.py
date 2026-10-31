# -*- coding: utf-8 -*-
"""Alertas do HUB-J FLUX.

1) Avisos de ações de outras pessoas (o admin escolhe quem acompanhar).
2) Lembretes de vencimento (cada usuário cria os seus).
Canais: sininho dentro do app + e-mail (opcional, por regra/lembrete)."""
import calendar
import hmac
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

import avisos_contas
import db
import email_service
from auth import login_required, requer_organizacao, requer_papel
from config import Config

alertas_bp = Blueprint("alertas", __name__)


def _brl(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _nome(usuario):
    return usuario.get("nome") or usuario.get("email") or "Alguém"


def _num_brl(texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _inteiro(valor, minimo, maximo, padrao=None):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return padrao
    return n if minimo <= n <= maximo else padrao


# ---------- Avisos de ação (quem acompanha quem) ----------

def registrar_acao(org_id, ator, titulo_curto, detalhe, link=None, pessoa_id=None):
    """Avisa quem acompanha esta ação. NUNCA derruba a ação principal: qualquer
    falha aqui é ignorada (a ação em si já foi gravada antes)."""
    try:
        try:
            pessoa_id = int(pessoa_id) if pessoa_id else None
        except (TypeError, ValueError):
            pessoa_id = None
        destinatarios = {}
        for r in db.regras_que_casam(org_id, ator["id"], pessoa_id):
            observador = r["observador_usuario_id"]
            if observador == ator["id"]:
                continue
            destinatarios[observador] = destinatarios.get(observador, False) or bool(r["por_email"])
        titulo = f"{_nome(ator)} · {titulo_curto}"
        for observador, por_email in destinatarios.items():
            db.criar_notificacao(org_id, observador, "acao", titulo, detalhe, link)
            if por_email:
                alvo = db.buscar_usuario_por_id(observador)
                if alvo and alvo.get("email"):
                    email_service.enviar_alerta(alvo["email"], titulo, detalhe, link)
    except Exception as e:
        print(f"[alertas] falha ao registrar ação (ignorada): {e}")
        try:
            db.get_conn().rollback()
        except Exception:
            pass


# ---------- Lembretes de vencimento ----------

def _vencimento(ano, mes, dia):
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def disparar_lembretes(org_id, hoje=None):
    """Cria os alertas de vencimento que já "entraram na janela" e ainda não foram
    enviados. Seguro de chamar várias vezes no dia (não repete) e recupera avisos
    de dias em que ninguém abriu o app, até o dia do vencimento."""
    hoje = hoje or date.today()
    disparados = 0
    try:
        seguinte = hoje + relativedelta(months=1)
        for l in db.lembretes_ativos_org(org_id):
            for ano, mes in ((hoje.year, hoje.month), (seguinte.year, seguinte.month)):
                venc = _vencimento(ano, mes, l["dia_mes"])
                aviso = venc - timedelta(days=l["dias_antes"])
                ultimo = l["ultimo_disparo"]
                if aviso <= hoje <= venc and (ultimo is None or ultimo < aviso):
                    quando = "vence hoje" if venc == hoje else f"vence em {(venc - hoje).days} dia(s), dia {venc:%d/%m}"
                    titulo = f"⏰ {l['nome']} {quando}"
                    detalhe = "Hora de conferir e pagar."
                    if l["valor_estimado"] is not None:
                        detalhe += f" Valor estimado: R$ {_brl(l['valor_estimado'])}."
                    db.criar_notificacao(org_id, l["usuario_id"], "lembrete", titulo, detalhe, "/lancamentos/novo?tipo=despesa")
                    if l["por_email"] and l.get("usuario_email"):
                        email_service.enviar_alerta(l["usuario_email"], titulo, detalhe, "/lancamentos/novo?tipo=despesa")
                    db.marcar_disparo_lembrete(l["id"], hoje)
                    disparados += 1
                    break
    except Exception as e:
        print(f"[alertas] falha ao disparar lembretes (ignorada): {e}")
        try:
            db.get_conn().rollback()
        except Exception:
            pass
    return disparados


# ---------- Telas ----------

@alertas_bp.route("/alertas")
@login_required
@requer_organizacao
def index():
    uid = g.usuario_atual["id"]
    itens = db.listar_notificacoes(uid)
    db.marcar_todas_lidas(uid)  # os itens abaixo ainda aparecem destacados como "novos" nesta visita
    return render_template("alertas.html", itens=itens)


@alertas_bp.route("/lembretes", methods=["GET", "POST"])
@login_required
@requer_organizacao
def lembretes():
    org_id, uid = g.usuario_atual["organizacao_id"], g.usuario_atual["id"]
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        dia = _inteiro(request.form.get("dia_mes"), 1, 31)
        if not nome or not dia:
            flash("Informe o nome e o dia do mês (1 a 31).", "erro")
            return redirect(url_for("alertas.lembretes"))
        db.criar_lembrete(org_id, uid, nome, dia, _inteiro(request.form.get("dias_antes"), 0, 15, 0),
                          _num_brl(request.form.get("valor_estimado")), request.form.get("por_email") == "on")
        flash(f"Lembrete \"{nome}\" criado.", "ok")
        return redirect(url_for("alertas.lembretes"))
    return render_template("lembretes.html", lembretes=db.listar_lembretes(org_id, uid))


@alertas_bp.route("/lembretes/<int:lembrete_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_lembrete(lembrete_id):
    dia = _inteiro(request.form.get("dia_mes"), 1, 31)
    nome = request.form.get("nome", "").strip()
    if not nome or not dia:
        flash("Informe o nome e o dia do mês (1 a 31).", "erro")
        return redirect(url_for("alertas.lembretes"))
    db.atualizar_lembrete(lembrete_id, g.usuario_atual["id"], nome, dia,
                          _inteiro(request.form.get("dias_antes"), 0, 15, 0),
                          _num_brl(request.form.get("valor_estimado")),
                          request.form.get("por_email") == "on", request.form.get("ativo") == "on")
    flash("Lembrete atualizado.", "ok")
    return redirect(url_for("alertas.lembretes"))


@alertas_bp.route("/lembretes/<int:lembrete_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_lembrete(lembrete_id):
    db.excluir_lembrete(lembrete_id, g.usuario_atual["id"])
    flash("Lembrete excluído.", "ok")
    return redirect(url_for("alertas.lembretes"))


@alertas_bp.route("/configuracoes/alertas", methods=["GET", "POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def config_alertas():
    org_id, uid = g.usuario_atual["organizacao_id"], g.usuario_atual["id"]
    usuarios = [u for u in db.listar_usuarios_por_organizacao(org_id) if u["id"] != uid]
    pessoas = db.listar_pessoas(org_id)

    if request.method == "POST":
        def modo(campo):
            return request.form.get(campo, "nao")
        regras = []
        if modo("obs_todos") != "nao":
            regras.append((None, None, modo("obs_todos") == "email"))
        for u in usuarios:
            m = modo(f"obs_u_{u['id']}")
            if m != "nao":
                regras.append((u["id"], None, m == "email"))
        for p in pessoas:
            m = modo(f"obs_p_{p['id']}")
            if m != "nao":
                regras.append((None, p["id"], m == "email"))
        db.salvar_observacoes(org_id, uid, regras)
        flash("Preferências de alertas salvas.", "ok")
        return redirect(url_for("alertas.config_alertas"))

    atuais = {}
    for r in db.listar_observacoes(org_id, uid):
        chave = "todos" if (r["observado_usuario_id"] is None and r["observado_pessoa_id"] is None) \
            else (f"u_{r['observado_usuario_id']}" if r["observado_usuario_id"] else f"p_{r['observado_pessoa_id']}")
        atuais[chave] = "email" if r["por_email"] else "app"
    return render_template("config_alertas.html", usuarios=usuarios, pessoas=pessoas, atuais=atuais)


@alertas_bp.route("/tarefas/lembretes")
def tarefa_lembretes():
    """Chamado todo dia por um agendador (cron) para garantir os avisos/e-mails
    mesmo que ninguém abra o app. Protegido por CRON_SECRET."""
    segredo = Config.CRON_SECRET
    if not segredo or not hmac.compare_digest(request.args.get("token", ""), segredo):
        abort(404)
    ids = db.listar_ids_organizacoes_ativas()
    total = sum(disparar_lembretes(oid) for oid in ids)
    contas = 0
    for oid in ids:
        try:
            contas += avisos_contas.disparar(oid)
        except Exception:  # uma organização com problema não pode impedir as outras de serem avisadas
            db.get_conn().rollback()
    return {"ok": True, "disparados": total, "avisos_contas": contas}
