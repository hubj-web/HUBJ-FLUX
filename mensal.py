# -*- coding: utf-8 -*-
"""Planejamento mensal (o que já está comprometido, mês a mês) + assistente de IA."""
import json
import re
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

import cartao_analise
import db
import empresa as empresa_mod
import ia
import planejamento_mensal as pm
from auth import login_required, requer_organizacao, requer_papel
from config import Config

mensal_bp = Blueprint("mensal", __name__, url_prefix="/mensal")

SUGESTOES = [
    "Quanto tenho livre em cada um dos próximos meses?",
    "Qual mês vai ser o mais apertado e por quê?",
    "Dá para parcelar uma compra de R$ 3.000 em 10x sem estourar o orçamento?",
    "O que eu poderia cortar para sobrar mais?",
    "Quando terminam minhas parcelas e quanto isso libera por mês?",
]


def _numero(texto):
    texto = (texto or "").strip()
    try:
        return float(texto.replace(".", "").replace(",", ".")) if texto else None
    except ValueError:
        return None


def _inteiro(texto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return None


def _carregar(org_id, n):
    """Junta tudo que o planejamento precisa: gastos fixos, cartão (faturas + parcelas) e renda."""
    hoje = date.today()
    fixos = [dict(f) for f in db.listar_gastos_fixos(org_id)]
    resumo = db.resumo_meses_cartao(org_id)
    ultimo = resumo[0]["mes_referencia"] if resumo else ""
    parcelas = cartao_analise.projetar_parcelas(db.compras_parceladas_cartao(org_id), ultimo, db.listar_compromissos(org_id))
    mes0 = hoje.strftime("%Y-%m")
    prefs = db.buscar_preferencias(org_id) or {}
    desloc = pm.calcular_deslocamento(resumo)
    meses = pm.visao_mensal(hoje, n, fixos, resumo, parcelas, db.renda_planejada_por_mes(org_id, mes0, cartao_analise.somar_meses(mes0, n - 1)),
                            prefs.get("renda_mensal"), desloc, db.empresa_cartao_por_mes(org_id))
    ultimo_caixa = cartao_analise.somar_meses(ultimo, desloc) if ultimo else ""
    return {"hoje": hoje, "mes_atual": mes0, "fixos": fixos, "resumo": resumo, "ultimo": ultimo, "meses": meses, "prefs": prefs,
            "renda_padrao": prefs.get("renda_mensal"), "media_fixos": pm.media_mensal(fixos),
            "cartao_defasado": bool(ultimo_caixa) and ultimo_caixa < mes0}


def _contexto_ia(org_id, d):
    """O QUE SAI DO APP PARA A IA. Só resumos e nomes de fornecedores/gastos. Nunca: nomes de pessoas,
    e-mails, nome da organização, descrições dos lançamentos ou observações."""
    meses = []
    for m in d["meses"]:
        meses.append({
            "mes": m["mes"], "renda": m["renda"], "gastos_fixos_total": m["total_fixos"],
            "gastos_fixos": [{"nome": i["nome"], "valor": i["valor"], "dia": i["dia"], "estimado": i["estimado"]} for i in m["fixos"]],
            "cartao_total": m["cartao"]["total"], "cartao_origem": m["cartao"]["origem"],
            "parcelas_do_cartao": [{"fornecedor": i["descricao"], "parcela": i["parcela"], "valor": round(i["valor"], 2)} for i in m["cartao"]["itens"]],
            "comprometido": m["comprometido"], "livre": m["livre"], "percentual_comprometido": m["pct"],
        })
    categorias = {c["id"]: c["nome"] for c in db.listar_categorias(org_id, apenas_ativas=False)}
    medias = sorted(((categorias.get(cid, "Sem categoria"), v) for cid, v in db.gasto_medio_categoria_ultimos_meses(org_id, d["mes_atual"]).items() if v > 0),
                    key=lambda x: -x[1])[:12]
    fornecedores = []
    if d["ultimo"]:
        fornecedores = [{"fornecedor": f["fornecedor"], "total": float(f["total"])} for f in db.gastos_por_fornecedor_cartao(org_id, d["ultimo"], 8)]
    metas = [{"nome": m["nome"], "alvo": float(m["valor_alvo"] or 0), "guardado": float(m["valor_atual"] or 0),
              "prazo": str(m["data_alvo"]) if m["data_alvo"] else None} for m in db.listar_metas(org_id)]
    avisos = []
    if not d["renda_padrao"] and not any(m["renda"] for m in d["meses"]):
        avisos.append("Renda mensal não informada: não é possível calcular quanto sobra.")
    if not d["fixos"]:
        avisos.append("Nenhum gasto fixo cadastrado ainda.")
    if not d["resumo"]:
        avisos.append("Nenhuma fatura de cartão importada ainda.")
    elif d["cartao_defasado"]:
        avisos.append(f"A última fatura importada é do mês {d['ultimo']}: o cartão dos meses seguintes mostra só parcelas já compradas.")
    return {"renda_mensal_padrao": float(d["renda_padrao"]) if d["renda_padrao"] else None, "meses": meses,
            "gasto_medio_mensal_por_categoria_ultimos_3_meses": [{"categoria": c, "media": v} for c, v in medias],
            "maiores_fornecedores_da_ultima_fatura": fornecedores, "metas": metas, "avisos": avisos}


def _sistema(org_id, d):
    return ia.montar_sistema(json.dumps(_contexto_ia(org_id, d), ensure_ascii=False), d["hoje"].isoformat())


def _bloqueio_ia(org_id):
    """None se pode chamar a IA; senão, a mensagem do motivo."""
    prefs = db.buscar_preferencias(org_id) or {}
    if not prefs.get("ia_ativa"):
        return "A IA está desligada para esta organização. Um administrador pode ligar em Assistente financeiro."
    if not ia.configurada():
        return "A IA ainda não foi configurada no servidor (falta a variável ANTHROPIC_API_KEY no Railway)."
    if db.contar_chamadas_ia(org_id) >= Config.IA_LIMITE_24H:
        return f"Limite de {Config.IA_LIMITE_24H} usos da IA nas últimas 24h atingido (trava de custo). Tente mais tarde."
    return None


def _gerar_analise(org_id, usuario_id, d):
    texto = ia.chamar(_sistema(org_id, d), [{"role": "user", "content": ia.PEDIDO_ANALISE}], max_tokens=1500)
    db.salvar_mensagem_ia(org_id, usuario_id, "analise", texto, d["mes_atual"])
    return db.ultima_analise_ia(org_id, d["mes_atual"])


# ---------- tela principal ----------

@mensal_bp.route("/")
@login_required
@requer_organizacao
def index():
    org_id = g.usuario_atual["organizacao_id"]
    n = _inteiro(request.args.get("n"))
    n = n if n in (3, 6, 12) else 6
    d = _carregar(org_id, n)
    ia_ativa = bool(d["prefs"].get("ia_ativa"))
    analise = db.ultima_analise_ia(org_id, d["mes_atual"]) if ia_ativa else None
    if ia_ativa and d["prefs"].get("ia_analise_automatica") and not analise and (d["fixos"] or d["resumo"]) and not _bloqueio_ia(org_id):
        try:
            analise = _gerar_analise(org_id, g.usuario_atual["id"], d)
        except ia.ErroIA as e:
            print(f"[mensal] análise automática não gerada: {e}")
    return render_template("mensal.html", n=n, ia_ativa=ia_ativa, ia_pronta=ia_ativa and ia.configurada(), analise=analise, **d)


@mensal_bp.route("/analisar", methods=["POST"])
@login_required
@requer_organizacao
def analisar():
    org_id = g.usuario_atual["organizacao_id"]
    motivo = _bloqueio_ia(org_id)
    if motivo:
        flash(motivo, "erro")
        return redirect(url_for("mensal.index"))
    try:
        _gerar_analise(org_id, g.usuario_atual["id"], _carregar(org_id, 6))
        flash("Análise atualizada.", "ok")
    except ia.ErroIA as e:
        flash(str(e), "erro")
    return redirect(url_for("mensal.index"))


# ---------- gastos fixos ----------

def _ler_gasto_fixo(criando):
    f = request.form
    nome, valor, dia = f.get("nome", "").strip(), _numero(f.get("valor")), _inteiro(f.get("dia_mes"))
    frequencia, inicio, fim = f.get("frequencia", "mensal"), f.get("mes_inicio", ""), f.get("mes_fim", "") or None
    erro = None
    if not nome or valor is None or valor <= 0:
        erro = "Informe o nome e um valor maior que zero."
    elif dia is None or not 1 <= dia <= 31:
        erro = "O dia do mês deve estar entre 1 e 31."
    elif frequencia not in pm.PASSO:
        erro = "Frequência inválida."
    elif not re.fullmatch(r"\d{4}-\d{2}", inicio):
        erro = "Escolha o mês de início."
    elif fim and (not re.fullmatch(r"\d{4}-\d{2}", fim) or fim < inicio):
        erro = "O mês de término não pode ser antes do início."
    if erro:
        return None, erro
    return {"nome": nome, "valor": valor, "estimado": f.get("estimado") == "on", "dia_mes": dia, "frequencia": frequencia,
            "mes_inicio": inicio, "mes_fim": fim, "no_cartao": f.get("no_cartao") == "on",
            "categoria_id": f.get("categoria_id") or None, "ativo": True if criando else f.get("ativo") == "on",
            "destino_empresa_id": empresa_mod.destino_valido(f.get("destino_empresa_id"), db.empresas_ids(g.usuario_atual["organizacao_id"]))}, None


@mensal_bp.route("/fixos", methods=["GET", "POST"])
@login_required
@requer_organizacao
def fixos():
    org_id = g.usuario_atual["organizacao_id"]
    if request.method == "POST":
        dados, erro = _ler_gasto_fixo(True)
        if erro:
            flash(erro, "erro")
        else:
            db.criar_gasto_fixo(org_id, dados)
            flash(f"\"{dados['nome']}\" cadastrado: já entra no planejamento dos próximos meses.", "ok")
        return redirect(url_for("mensal.fixos"))
    lista = db.listar_gastos_fixos(org_id)
    return render_template("mensal_fixos.html", fixos=lista, media=pm.media_mensal(lista), rotulos=pm.ROTULO_FREQUENCIA,
                           categorias=db.listar_categorias(org_id, tipo="despesa"), mes_atual=date.today().strftime("%Y-%m"))


@mensal_bp.route("/fixos/<int:gasto_id>/salvar", methods=["POST"])
@login_required
@requer_organizacao
def salvar_fixo(gasto_id):
    dados, erro = _ler_gasto_fixo(False)
    if erro:
        flash(erro, "erro")
    else:
        db.atualizar_gasto_fixo(gasto_id, g.usuario_atual["organizacao_id"], dados)
        flash("Gasto atualizado.", "ok")
    return redirect(url_for("mensal.fixos"))


@mensal_bp.route("/fixos/<int:gasto_id>/excluir", methods=["POST"])
@login_required
@requer_organizacao
def excluir_fixo(gasto_id):
    db.excluir_gasto_fixo(gasto_id, g.usuario_atual["organizacao_id"])
    flash("Gasto excluído.", "ok")
    return redirect(url_for("mensal.fixos"))


# ---------- assistente ----------

@mensal_bp.route("/assistente")
@login_required
@requer_organizacao
def assistente():
    org_id, uid = g.usuario_atual["organizacao_id"], g.usuario_atual["id"]
    prefs = db.buscar_preferencias(org_id) or {}
    return render_template("mensal_assistente.html", prefs=prefs, ia_ativa=bool(prefs.get("ia_ativa")), ia_configurada=ia.configurada(),
                           mensagens=db.listar_mensagens_ia(org_id, uid, 40), sugestoes=SUGESTOES, prefill=request.args.get("q", ""),
                           restantes=max(0, Config.IA_LIMITE_24H - db.contar_chamadas_ia(org_id)), limite=Config.IA_LIMITE_24H,
                           eh_admin=g.usuario_atual["papel"] in ("super_admin", "admin_cliente"))


@mensal_bp.route("/assistente/perguntar", methods=["POST"])
@login_required
@requer_organizacao
def perguntar():
    org_id, uid = g.usuario_atual["organizacao_id"], g.usuario_atual["id"]
    pergunta = (request.form.get("pergunta") or "").strip()
    if len(pergunta) < 3:
        flash("Escreva a sua pergunta.", "erro")
        return redirect(url_for("mensal.assistente"))
    if len(pergunta) > 600:
        flash("Pergunta muito longa (máximo de 600 caracteres).", "erro")
        return redirect(url_for("mensal.assistente", q=pergunta[:600]))
    motivo = _bloqueio_ia(org_id)
    if motivo:
        flash(motivo, "erro")
        return redirect(url_for("mensal.assistente", q=pergunta))
    historico = ia.montar_historico(db.listar_mensagens_ia(org_id, uid, 10), pergunta)
    try:
        texto = ia.chamar(_sistema(org_id, _carregar(org_id, 6)), historico, max_tokens=1200)
    except ia.ErroIA as e:
        flash(str(e), "erro")
        return redirect(url_for("mensal.assistente", q=pergunta))  # a pergunta volta para a caixa, nada se perde
    db.salvar_mensagem_ia(org_id, uid, "pergunta", pergunta)
    db.salvar_mensagem_ia(org_id, uid, "resposta", texto)
    return redirect(url_for("mensal.assistente") + "#fim")


@mensal_bp.route("/ia/config", methods=["POST"])
@login_required
@requer_organizacao
@requer_papel("super_admin", "admin_cliente")
def config_ia():
    ativa, auto = request.form.get("ia_ativa") == "on", request.form.get("ia_analise_automatica") == "on"
    db.salvar_config_ia(g.usuario_atual["organizacao_id"], ativa, auto and ativa)
    if ativa and not ia.configurada():
        flash("IA ligada, mas falta configurar a chave no servidor (variável ANTHROPIC_API_KEY no Railway).", "erro")
    else:
        flash("IA ligada para esta organização." if ativa else "IA desligada: nada será enviado.", "ok")
    return redirect(url_for("mensal.assistente"))


@mensal_bp.route("/ia/contexto")
@login_required
@requer_organizacao
def contexto():
    org_id = g.usuario_atual["organizacao_id"]
    d = _carregar(org_id, 6)
    return render_template("mensal_contexto.html", instrucoes=ia.INSTRUCOES,
                           dados=json.dumps(_contexto_ia(org_id, d), ensure_ascii=False, indent=2))


@mensal_bp.route("/ia/limpar", methods=["POST"])
@login_required
@requer_organizacao
def limpar_conversa():
    db.limpar_mensagens_ia(g.usuario_atual["organizacao_id"], g.usuario_atual["id"])
    flash("Conversa apagada.", "ok")
    return redirect(url_for("mensal.assistente"))
