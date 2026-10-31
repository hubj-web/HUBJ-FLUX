# -*- coding: utf-8 -*-
"""Trilha guiada: o passo a passo para ensinar o cliente a controlar o dinheiro da família e o da empresa, SEPARADOS.
Cada passo explica o porquê, leva à tela certa e se marca sozinho quando o app detecta que foi feito ('auto'). O resto o cliente marca à mão ('manual')."""

# chave, título, por quê, link, auto?, módulo exigido (ou None), só se o cliente tem empresa?
FAMILIA = [
    ("contas", "Cadastre suas contas bancárias", "Saber quanto você tem em cada conta é o ponto de partida de qualquer controle. Cadastre as contas pessoais, com o saldo de hoje.", "/configuracoes/contas", True, None, False),
    ("lancar", "Lance os primeiros gastos e entradas", "O aplicativo só ajuda se tiver o que somar. Lance pelo menos 5 movimentos reais para ver o Mês ganhar vida.", "/lancamentos/novo", True, None, False),
    ("cartao", "Importe a fatura do cartão", "A fatura é onde costuma estar a maior parte dos gastos. Importando o PDF, cada compra entra sozinha.", "/cartao/importar", True, None, False),
    ("categorizar", "Categorize as compras do cartão", "Sem categoria, o relatório não diz para onde o dinheiro foi. Categorizando os maiores fornecedores de uma vez, você resolve a maior parte.", "/cartao/categorizar/", True, None, False),
    ("planejar", "Planeje o mês", "Planejar é decidir o limite de cada categoria antes de gastar. O Controle depois mostra se você cumpriu.", "/planejamento/", True, None, False),
    ("separar_familia", "Pague gastos pessoais só com dinheiro pessoal", "Misturar os dois bolsos é o erro mais comum de quem tem empresa: o saldo da família deixa de dizer a verdade, e a empresa parece dar mais ou menos lucro do que realmente dá.", None, False, None, True),
    ("prolabore_familia", "Registre o pró-labore que a empresa paga a você", "O pró-labore é o seu salário de sócio. Registrando como transferência, ele entra como renda da família e como despesa da empresa, uma vez só.", "/entre-espacos/nova", True, "transferencias", True),
    ("ver_total", "Olhe o seu dinheiro total", "Família e empresa juntas mostram o quadro inteiro, sem contar em dobro o que só passou de um bolso para o outro.", "/consolidado/", False, "consolidado", True),
]
EMPRESA = [
    ("contas_pj", "Cadastre a conta bancária DA EMPRESA", "A regra número um: conta da empresa e conta pessoal nunca se misturam. Cadastre aqui só a conta (ou as contas) da empresa.", "/configuracoes/contas", True, None, False),
    ("parceiros", "Cadastre clientes e fornecedores", "Saber quem deve a você e a quem você deve é a base para cobrar e para pagar em dia.", "/contas/parceiros", True, "contas_pagar_receber", False),
    ("contas_pagar", "Cadastre as contas a pagar", "Aluguel, fornecedores, impostos: tudo com vencimento. O aplicativo avisa antes de vencer, e você nunca paga multa por esquecimento.", "/contas/novo?tipo=pagar", True, "contas_pagar_receber", False),
    ("contas_receber", "Cadastre o que você tem a receber", "Vendas a prazo e serviços já feitos entram aqui. É o que alimenta o fluxo de caixa previsto.", "/contas/novo?tipo=receber", True, "contas_pagar_receber", False),
    ("prolabore", "Defina e registre o seu pró-labore", "Tire dinheiro da empresa de duas formas só: pró-labore (o salário) e distribuição de lucros. Nunca pagando conta pessoal direto do caixa da empresa.", "/entre-espacos/nova", True, "transferencias", False),
    ("impostos", "Crie os lembretes de impostos", "DAS, FGTS Digital e as declarações anuais têm data certa. O lembrete avisa com folga, e você confere a data na guia.", "/financeiro/impostos", True, "resultado_caixa", False),
    ("reserva_imposto", "Separe uma parte de cada venda para os impostos", "O imposto não é do dono da empresa. Reserve o valor assim que a venda entra, para não faltar no dia do vencimento.", None, False, None, False),
    ("resultado", "Olhe o resultado e o fluxo de caixa todo mês", "Lucro e caixa são coisas diferentes: uma empresa pode dar lucro e ficar sem dinheiro. Olhar os dois todo mês evita surpresa.", "/financeiro/resultado", False, "resultado_caixa", False),
]


def passos(tipo, modulos_ativos, tem_empresa):
    """Os passos que valem para este espaço: some o que depende de módulo desligado e o que só faz sentido para quem tem empresa."""
    lista = EMPRESA if tipo == "empresa" else FAMILIA
    out = []
    for chave, titulo, por_que, link, auto, modulo, so_com_empresa in lista:
        if modulo and not modulos_ativos.get(modulo):
            continue
        if so_com_empresa and not tem_empresa:
            continue
        out.append({"chave": chave, "titulo": titulo, "por_que": por_que, "link": link, "auto": auto})
    return out


def montar(passos_lista, feitos_auto, marcas):
    """Junta os passos com o que está feito. Devolve a lista, quantos estão feitos e o próximo passo."""
    itens = [{**p, "feito": bool(feitos_auto.get(p["chave"])) if p["auto"] else p["chave"] in marcas} for p in passos_lista]
    n = sum(1 for i in itens if i["feito"])
    return {"passos": itens, "feitos": n, "total": len(itens), "pct": round(n / len(itens) * 100) if itens else 100, "proximo": next((i for i in itens if not i["feito"]), None)}
