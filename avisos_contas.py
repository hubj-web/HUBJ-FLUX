# -*- coding: utf-8 -*-
"""Aviso de vencimento das contas a pagar e a receber (sininho): o administrador é avisado, uma vez só por situação, quando
- uma conta A PAGAR vence hoje ou nos próximos 3 dias;
- uma conta A PAGAR venceu e continua em aberto;
- uma conta A RECEBER está atrasada.
Quem baixa, cancela ou edita a conta zera os avisos dela. Se muitas contas vencem de uma vez, vira um aviso só (para não inundar o sininho)."""
from datetime import date, timedelta

import db
import modulos
from db import execute, query_all

DIAS_ANTES = 3
LIMITE_INDIVIDUAIS = 5   # acima disso, um aviso resumido por tipo


def _admins(organizacao_id):
    return [r["id"] for r in query_all(
        """SELECT DISTINCT u.id FROM usuarios u JOIN acessos a ON a.usuario_id = u.id
           WHERE a.organizacao_id = %s AND a.papel = 'admin_cliente' AND u.status <> 'bloqueado'""", (organizacao_id,))]


def _brl(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _avisar(org_id, admins, titulo, mensagem, link):
    for uid in admins:
        db.criar_notificacao(org_id, uid, "conta_vencimento", titulo, mensagem, link)


def _marcar(titulo_ids, fase):
    for tid in titulo_ids:
        execute("INSERT INTO titulos_avisos (titulo_id, fase) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tid, fase))


def disparar(organizacao_id, hoje=None):
    """Cria os avisos que faltam. Devolve quantos avisos (situações) foram gerados. Sem o módulo de contas ligado, não faz nada."""
    hoje = hoje or date.today()
    if not modulos.modulo_ativo(organizacao_id, "contas_pagar_receber"):
        return 0
    rows = query_all(
        """SELECT t.id, t.tipo, t.descricao, t.valor, t.vencimento, p.nome AS parceiro,
                  CASE WHEN t.vencimento < %(h)s THEN 'vencido' ELSE 'proximo' END AS fase
           FROM titulos t LEFT JOIN parceiros p ON p.id = t.parceiro_id
           WHERE t.organizacao_id = %(o)s AND t.status = 'aberto'
             AND ((t.tipo = 'pagar' AND t.vencimento <= %(h)s + %(d)s) OR (t.tipo = 'receber' AND t.vencimento < %(h)s))
             AND NOT EXISTS (SELECT 1 FROM titulos_avisos a WHERE a.titulo_id = t.id
                             AND a.fase = CASE WHEN t.vencimento < %(h)s THEN 'vencido' ELSE 'proximo' END)
           ORDER BY t.vencimento, t.id""",
        {"o": organizacao_id, "h": hoje, "d": DIAS_ANTES})
    if not rows:
        return 0
    admins = _admins(organizacao_id)
    if not admins:
        return 0
    n = 0
    for tipo, fase in (("pagar", "proximo"), ("pagar", "vencido"), ("receber", "vencido")):
        grupo = [r for r in rows if r["tipo"] == tipo and r["fase"] == fase]
        if not grupo:
            continue
        if len(grupo) > LIMITE_INDIVIDUAIS:
            total = sum(float(r["valor"]) for r in grupo)
            nome = "a pagar" if tipo == "pagar" else "a receber"
            if fase == "vencido":
                _avisar(organizacao_id, admins, f"🔴 Você tem {len(grupo)} contas {nome} vencidas (R$ {_brl(total)})", "Toque para ver a lista.",
                        f"/contas/?tipo={tipo}&situacao=vencidos")
            else:
                _avisar(organizacao_id, admins, f"💸 {len(grupo)} contas a pagar vencem nos próximos {DIAS_ANTES} dias (R$ {_brl(total)})", "Toque para ver a lista.", "/contas/?tipo=pagar")
            n += 1
        else:
            for r in grupo:
                dias = (r["vencimento"] - hoje).days
                quem = f"{r['parceiro']} · " if r["parceiro"] else ""
                det = f"{quem}vence em {r['vencimento'].strftime('%d/%m/%Y')} · R$ {_brl(r['valor'])}"
                if fase == "proximo":
                    quando = "vence HOJE" if dias == 0 else f"vence em {dias} dia(s)"
                    _avisar(organizacao_id, admins, f"💸 Conta a pagar {quando}: {r['descricao']}", det, f"/contas/{r['id']}/baixar")
                elif tipo == "pagar":
                    _avisar(organizacao_id, admins, f"🔴 Conta a pagar vencida há {-dias} dia(s): {r['descricao']}", det, f"/contas/{r['id']}/baixar")
                else:
                    _avisar(organizacao_id, admins, f"⚠️ Conta a receber atrasada há {-dias} dia(s): {r['descricao']}", det, f"/contas/{r['id']}/baixar")
                n += 1
        _marcar([r["id"] for r in grupo], fase)
    return n
