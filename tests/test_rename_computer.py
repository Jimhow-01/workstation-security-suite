"""Testes da geracao de nome de estacao.

`rename_computer.py` importa ctypes (ok em qualquer plataforma) mas as funcoes de
rename usam `ctypes.windll` e `subprocess` - essas nao sao testadas aqui. O que se
testa e a politica de naming, que e pura.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "onboarding"))

import rename_computer  # noqa: E402


def test_default_format_is_prefix_plus_four_digits():
    name = rename_computer.gerar_novo_nome()
    assert re.fullmatch(r"WS-\d{4}", name), name


def test_custom_prefix_and_length():
    name = rename_computer.gerar_novo_nome(prefixo="DEV-", tamanho=6)
    assert re.fullmatch(r"DEV-\d{6}", name), name


def test_names_are_random_across_calls():
    """A aleatoriedade importa: duas maquinas novas nao podem nascer com o mesmo nome."""
    names = {rename_computer.gerar_novo_nome() for _ in range(200)}
    assert len(names) > 100


def test_name_is_valid_windows_computer_name():
    """NetBIOS aceita ate 15 caracteres, sem espaco e sem caracteres reservados."""
    name = rename_computer.gerar_novo_nome()
    assert len(name) <= 15
    assert re.fullmatch(r"[A-Za-z0-9-]+", name)
