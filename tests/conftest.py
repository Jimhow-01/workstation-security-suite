"""Define o ambiente que os modulos esperam antes de serem importados.

`lock/unlock_keygen.py` e `monitor/cerberus_agent.py` leem variaveis de ambiente no
escopo do modulo - sem isso o import quebra antes de qualquer teste rodar.
"""
import os

os.environ.setdefault("HMAC_SECRET", "test-secret-not-a-real-one")
# chave Fernet valida mas de entropia zero: e placeholder, e nao dispara scanner de segredos
os.environ.setdefault("AGENT_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
