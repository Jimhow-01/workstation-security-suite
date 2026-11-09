import json
import os
import time

import requests
import win32evtlog
import win32evtlogutil

print("iniciando")

# Enviar dados para o Firebase (sem autenticação)
def send_to_firebase(software_name, user, event_time, description):
    url = os.environ["FIREBASE_DATABASE_URL"] + "/installations.json"
    data = {
        'software_name': software_name,
        'user': user,
        'event_time': event_time,
        'description': description
    }
    response = requests.post(url, data=json.dumps(data))
    if response.status_code == 200:
        print("Dados enviados ao Firebase com sucesso.")
    else:
        print(f"Falha ao enviar dados ao Firebase. Status: {response.status_code}")

# Função para monitorar o log de eventos
def monitor_event_log():
    server = 'localhost'
    log_type = 'Security'
    log_handle = win32evtlog.OpenEventLog(server, log_type)
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    record_offset = 0

    while True:
        events = win32evtlog.ReadEventLog(log_handle, flags, record_offset)
        if events:
            for event in events:
                event_id = event.EventID
                time_generated = event.TimeGenerated.Format()  # Data e hora do evento
                username = event.StringInserts[1] if event.StringInserts else 'Desconhecido'
                event_message = win32evtlogutil.SafeFormatMessage(event, log_type)

                # FIXME: EventID 4663 e "An attempt was made to access an object",
                # nao um evento de instalacao de software. Funciona como sinal
                # aproximado (instalar gera acesso a arquivos), mas a fonte correta
                # seria a chave Uninstall do registro, Win32_Product, ou os EventIDs
                # 101/103 do log de Aplicativo (Windows Installer).
                if event_id == 4663:  # NOTE: proxy de instalacao, nao instalacao real
                    print("Software instalado detectado:")
                    print(f"Usuário: {username}")
                    print(f"Data e Hora: {time_generated}")
                    print(f"Descrição: {event_message}")
                    print('-' * 50)

                    # Enviar informações para o Firebase
                    send_to_firebase("Software Desconhecido", username, time_generated, event_message)
        else:
            time.sleep(10)  # Intervalo antes de verificar novamente

if __name__ == "__main__":
    monitor_event_log()
