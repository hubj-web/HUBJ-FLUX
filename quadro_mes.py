# -*- coding: utf-8 -*-
"""Monta o quadro da tela do Mês: planejado x realizado da FAMÍLIA (mesma conta do Controle).

planejado_por_categoria: {categoria_id: limite}
realizado_por_categoria: {categoria_id | None: valor}   (None = gasto sem categoria)
nomes: {categoria_id: nome}
"""
import math

import regras_negocio


def arredondar_limite(valor):
    """Limite sugerido: dezena de reais mais próxima, com a metade para cima (25 vira 30, não 20); mínimo R$ 10 quando há gasto."""
    if valor is None or valor <= 0:
        return 0.0
    return float(max(10, math.floor(valor / 10 + 0.5) * 10))


def _pct(real, plan):
    return round(real / plan * 100) if plan else None


def montar_quadro(planejado_por_categoria, realizado_por_categoria, nomes):
    limites = {c: float(v) for c, v in planejado_por_categoria.items() if v and float(v) > 0}
    realizado_total = round(sum(realizado_por_categoria.values()), 2)
    planejado_total = round(sum(limites.values()), 2)
    dentro_do_plano = round(sum(realizado_por_categoria.get(c, 0.0) for c in limites), 2)
    fora_do_plano = round(realizado_total - dentro_do_plano, 2)
    sem_categoria = round(realizado_por_categoria.get(None, 0.0), 2)

    ids = set(limites) | {c for c, v in realizado_por_categoria.items() if c is not None and v > 0}
    linhas = []
    for cid in ids:
        plan, real = limites.get(cid, 0.0), round(realizado_por_categoria.get(cid, 0.0), 2)
        estado, cor = regras_negocio.calcular_semaforo(real, plan)
        pct = _pct(real, plan)
        linhas.append({"categoria_id": cid, "nome": nomes.get(cid, "Categoria"), "planejado": plan, "realizado": real,
                       "pct": pct, "estado": estado, "cor": cor, "barra": min(100, pct) if pct is not None else 0})
    linhas.sort(key=lambda l: (-l["realizado"], l["nome"]))

    estado, cor = regras_negocio.calcular_semaforo(dentro_do_plano, planejado_total)
    pct = _pct(dentro_do_plano, planejado_total)
    return {
        "tem_plano": planejado_total > 0, "planejado_total": planejado_total, "realizado_total": realizado_total,
        "dentro_do_plano": dentro_do_plano, "fora_do_plano": fora_do_plano, "sem_categoria": sem_categoria,
        "restante": round(planejado_total - dentro_do_plano, 2), "pct": pct, "estado": estado, "cor": cor,
        "barra": min(100, pct) if pct is not None else 0, "linhas": linhas,
        "estourados": [l for l in linhas if l["cor"] == "vermelho"],
    }
