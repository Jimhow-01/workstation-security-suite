import datetime
import os
import socket
import subprocess

import requests

# Aponta para um nó "ips" e termina com .json (POST gera uma chave única)
FIREBASE_URL = os.environ["FIREBASE_DATABASE_URL"] + "/ips.json"

# Captura a saída do ipconfig com a codificação do console do Windows
output = subprocess.run(
    ['ipconfig'],
    capture_output=True,
    text=True,
    encoding='cp850',   # se ainda vier estranho, tente 'latin1' ou remova para usar o padrão
).stdout

def enviar():
    recovery_data = {
        "hostname": socket.gethostname(),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "ipconfig_raw": output
    }

    try:
        resp = requests.post(FIREBASE_URL, json=recovery_data, timeout=10)
        if resp.ok:
            print(f"Enviado com sucesso: {resp.json()}")
        else:
            print(f"Falha ao enviar. Status: {resp.status_code}")
            print("Resposta:", resp.text)
    except Exception as e:
        print("Erro na requisição:", e)

if __name__ == "__main__":
    enviar()
