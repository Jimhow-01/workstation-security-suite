import getpass
import os
import socket
import subprocess
import time
from datetime import datetime

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def restart_explorer():
    # Encerra o processo explorer.exe
    os.system("taskkill /f /im explorer.exe")
    
    # Reinicia o explorer.exe
    subprocess.Popen("explorer.exe")

def check_internet(host="8.8.8.8", port=53, timeout=3):
    """
    Verifica se há conexão com a internet tentando se conectar ao DNS do Google.
    
    Args:
    host (str): Endereço IP para tentar se conectar (default é o DNS do Google).
    port (int): Porta para tentar se conectar (default é 53).
    timeout (int): Tempo limite para a conexão em segundos (default é 3).

    Returns:
    bool: Retorna True se a conexão for bem-sucedida (há internet), False caso contrário.
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except OSError as ex:
        print(f"Sem conexão com a internet: {ex}")
        restart_explorer()
        return False
    

class CopyEventHandler(FileSystemEventHandler):
    def __init__(self, source, watch_list):
        self.source = source
        self.watch_list = watch_list
        self.source_drive = os.path.splitdrive(source)[0]

    def on_modified(self, event):
        if event.is_directory:
            return

        # Obtém a unidade de disco do caminho do arquivo modificado
        event_drive = os.path.splitdrive(event.src_path)[0]

        # Cria o caminho de origem baseado no evento
        source_path = os.path.join(self.source, os.path.relpath(event.src_path, event_drive + '\\'))

        # Verifica se o arquivo foi copiado para um disco diferente do disco de origem
        if os.path.splitdrive(source_path)[0].lower() != os.path.splitdrive(event.src_path)[0].lower():
            if os.path.exists(source_path):
                # Verifica se alguma palavra da lista está presente no caminho do arquivo
                for term in self.watch_list:
                    if term in event.src_path or term in source_path:
                        check_internet(host="8.8.8.8", port=53, timeout=3)
                        print(f"Atenção: A palavra '{term}' foi encontrada no caminho: {event.src_path}\n")
                        
                        # Imprime o caminho de origem
                        print(f'Arquivo copiado de: {source_path}\n')
                
                        # Imprime o caminho completo do arquivo copiado
                        print(f'Arquivo copiado para: {event.src_path}\n\n\n')
                        
                        # Chama a função firebase_funcao com os caminhos relevantes
                        firebase_funcao(source_path, event.src_path)


def get_svn_user():
    auth_dir = os.path.join(os.getenv('APPDATA'), 'Subversion', 'auth', 'svn.simple')
    
    if not os.path.exists(auth_dir):
        print("Pasta de configuração não encontrada.")
        return None
    
    for root, dirs, files in os.walk(auth_dir):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path) as f:
                lines = f.readlines()
                for i in range(len(lines)):
                    if lines[i].strip() == 'username':
                        if i + 2 < len(lines):
                            username = lines[i + 2].strip()
                            return username

get_svn_user()

def nomedopc():
    computer_name = socket.gethostname() 
    return computer_name

nomedopc()

def verificar_nomeatual():
    # Obtém o nome do usuário atual
    usuario_atual = getpass.getuser().lower()
    return usuario_atual

usuario_atual = verificar_nomeatual() 

def get_ip_location():
    try:
        # Obtém o IP público
        ip_response = requests.get('https://api.ipify.org?format=json')
        ip_data = ip_response.json()
        ip_address = ip_data['ip']
        
        # Obtém a localização com base no IP
        location_response = requests.get(f'https://ipinfo.io/{ip_address}/json')
        location_data = location_response.json()
        
        # Extraindo informações relevantes
        location = {
            'IP': ip_address,
            'City': location_data.get('city', 'N/A'),
            'Region': location_data.get('region', 'N/A'),
            'Country': location_data.get('country', 'N/A'),
            'Location': location_data.get('loc', 'N/A')
        }
        
        cidade =  location_data.get('city', 'N/A')
        
        return cidade
    except Exception as e:
        return {'Error': str(e)}

location = get_ip_location()
print("Localização do PC:")
print(location)

def fetch_watch_list_from_firebase():
    firebase_url = os.environ["FIREBASE_DATABASE_URL"] + "/.json"
    try:
        response = requests.get(firebase_url)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "watch_list" in data:
                return data["watch_list"]
        else:
            print(f"Erro ao acessar o Firebase: {response.status_code}")
    except Exception as e:
        print(f"Erro ao obter dados do Firebase: {e}")
    return []

def monitor_directories(source, watch_list):
    # Verifica se o diretório existe
    if not os.path.exists(source):
        print(f"O diretório de origem '{source}' não existe.")
        return

    # Busca os termos adicionais do Firebase
    firebase_watch_list = fetch_watch_list_from_firebase()
    
    # Combina a lista estática com a lista obtida do Firebase
    watch_list += firebase_watch_list
    
    event_handler = CopyEventHandler(source, watch_list)
    observer = Observer()
    
    # Monitora o diretório de origem
    observer.schedule(event_handler, path=source, recursive=True)
    
    # Monitora todos os discos presentes, exceto o de origem
    for drive in [f'{chr(x)}:\\' for x in range(65, 91) if os.path.exists(f'{chr(x)}:\\') and f'{chr(x)}:\\' != source]:
        observer.schedule(event_handler, path=drive, recursive=True)
    
    observer.start()
    print(f'Monitorando o diretório de origem: {source}')
    print('Monitorando todos os discos, exceto o de origem.')
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

def firebase_funcao(raiz, destino):
    now = datetime.now()
    current_date_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    print("Data e horário atual:", current_date_time)
    
    dados = {
        'raiz': raiz,
        'destino': destino,
        'data_hora': current_date_time,
        'Local': location
    }
    
    computer_name = nomedopc()
    svnuser = get_svn_user() or "none"  # Usa "none" se svnuser for None
    
    if svnuser == "none":
        svnuser = usuario_atual
    
    invalid_chars = "[]/.#$"
    computer_name_safe = "".join(c if c not in invalid_chars else "_" for c in computer_name)
    svnuser_safe = "".join(c if c not in invalid_chars else "_" for c in svnuser)
    
    computer_name2 = f'{computer_name_safe} - {svnuser_safe}'
    
    link_firebase = os.environ["FIREBASE_DATABASE_URL"] + "/"

    requesicao = requests.post(f'{link_firebase}/{computer_name2}/.json', json=dados)
    print(requesicao)
    print(requesicao.text)


if __name__ == "__main__":
    try:
        # Obtém o diretório onde o script está localizado
        script_directory = os.path.dirname(os.path.abspath(__file__))
        # Obtém a unidade do disco do diretório do script
        drive_letter = os.path.splitdrive(script_directory)[0]
        
        # Define o diretório de origem como a unidade do disco
        source_directory = drive_letter + '\\'
        
        # Lista de palavras a serem monitoradas
        watch_list = [
            # palavras-chave que identificam conteudo de projeto de jogo
            # (exemplo generico - ajuste ao seu ambiente)
            "Content", "Source", "Plugins", "Build", "Config", "Binaries",
            "Intermediate", "DerivedDataCache", "Saved", "Maps", "Meshes",
            "Textures", "Materials", "Blueprints", "Animations", "Audio",
            "ProjectAlpha.uproject", "ProjectAlpha.png",
        ]
        
        # Inicia o monitoramento
        monitor_directories(source_directory, watch_list)
    except ConnectionError: 
        pass
    except socket.gaierror:
        pass
