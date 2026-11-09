"""Testes da verificacao de integridade e do estado cifrado do agente.

`cerberus_agent.py` usa `winreg` e fala com nos de monitoramento, entao o modulo
so importa no Windows. Os testes cobrem as duas partes puras: o SHA-256 usado para
verificar download e o round-trip de cifragem Fernet do estado local.
"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "monitor"))

pytest.importorskip("winreg", reason="cerberus_agent depende de winreg (Windows-only)")

import cerberus_agent  # noqa: E402


def test_calculate_file_hash_matches_sha256(tmp_path):
    f = tmp_path / "payload.bin"
    payload = b"conteudo de teste" * 5000
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert cerberus_agent.calculate_file_hash(str(f)) == expected


def test_calculate_file_hash_of_missing_file_returns_empty(tmp_path):
    """O contrato do codigo e devolver string vazia em falha, nao lancar."""
    assert cerberus_agent.calculate_file_hash(str(tmp_path / "nao-existe.bin")) == ""


def test_hash_differs_for_different_content(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"um conteudo")
    b.write_bytes(b"outro conteudo")
    assert cerberus_agent.calculate_file_hash(str(a)) != cerberus_agent.calculate_file_hash(str(b))


def test_encrypted_state_round_trip(tmp_path):
    path = str(tmp_path / "state.enc")
    data = {"hostname": "WS-0001", "programs": ["a", "b"], "nested": {"x": 1}}
    cerberus_agent.save_encrypted_data(data, path)
    assert cerberus_agent.load_encrypted_data(path) == data


def test_saved_state_is_not_plaintext(tmp_path):
    path = str(tmp_path / "state.enc")
    secret = "WS-0001"
    cerberus_agent.save_encrypted_data({"hostname": secret}, path)
    raw = Path(path).read_bytes()
    assert secret.encode() not in raw
    assert b"hostname" not in raw


def test_load_missing_file_returns_none(tmp_path):
    assert cerberus_agent.load_encrypted_data(str(tmp_path / "ausente.enc")) is None
