"""Testes do keygen HMAC de desbloqueio da estacao.

Cobrem o contrato real do desbloqueio: a chave derivada do ID e deterministica,
tem exatamente 12 caracteres base64-url, e corresponde ao calculo que a estacao
verifica em `lock_workstation.hmac_verify_id`.
"""
import base64
import hashlib
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lock"))

import unlock_keygen  # noqa: E402


def test_generate_hmac_is_deterministic():
    assert unlock_keygen.generate_hmac(123456) == unlock_keygen.generate_hmac(123456)


def test_generate_hmac_length_and_charset():
    key = unlock_keygen.generate_hmac(9876543210)
    assert len(key) == 12
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(key) <= allowed


def test_generate_hmac_matches_reference_implementation():
    """HMAC-SHA256 do ID em base64-url, truncado em 12 - o mesmo calculo da estacao."""
    secret = os.environ["HMAC_SECRET"].encode()
    expected = base64.urlsafe_b64encode(
        hmac.new(secret, b"4242", hashlib.sha256).digest()
    )[:12].decode()
    assert unlock_keygen.generate_hmac(4242) == expected


def test_different_ids_give_different_keys():
    assert unlock_keygen.generate_hmac(1) != unlock_keygen.generate_hmac(2)


def test_key_changes_when_secret_changes(monkeypatch):
    original = unlock_keygen.SECRET_KEY
    monkeypatch.setattr(unlock_keygen, "SECRET_KEY", b"outro-segredo")
    with_other = unlock_keygen.generate_hmac(4242)
    monkeypatch.setattr(unlock_keygen, "SECRET_KEY", original)
    assert with_other != unlock_keygen.generate_hmac(4242)
