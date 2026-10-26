# -*- coding: utf-8 -*-
"""Conferências simples de dados que chegam dos formulários."""
import re

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
PAPEIS_CONVIDAVEIS = ("membro", "admin_cliente")  # quem administra uma família nunca pode criar um Super Admin


def email_valido(email):
    return bool(email) and len(email) <= 254 and _EMAIL.match(email) is not None
