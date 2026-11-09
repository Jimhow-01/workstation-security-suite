import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import Tk, messagebox

import psutil
import requests
import schedule  # Para agendar a tarefa de enviar o log às 11h
import win32api
import win32con
import win32file
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# --- Garantia de constante ---
if not hasattr(win32con, "FILE_LIST_DIRECTORY"):
    win32con.FILE_LIST_DIRECTORY = 0x0001

WATCH_DIR = os.environ.get('WATCH_DIR', str(Path.home() / 'security-requests'))
LOG_PATH = str(Path.cwd() / 'uac_watcher.log')

# --- Funções auxiliares ---
def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} - {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def set_uac_values_subprocess(consent_behavior: int, prompt_secure_desktop: int):
    """
    Altera valores do UAC usando reg.exe via subprocess.
    """
    try:
        comando1 = [
            "reg", "add",
            r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
            "/v", "ConsentPromptBehaviorAdmin",
            "/t", "REG_DWORD", "/d", str(consent_behavior), "/f"
        ]
        comando2 = [
            "reg", "add",
            r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
            "/v", "PromptOnSecureDesktop",
            "/t", "REG_DWORD", "/d", str(prompt_secure_desktop), "/f"
        ]

        r1 = subprocess.run(comando1, capture_output=True, text=True)
        r2 = subprocess.run(comando2, capture_output=True, text=True)

        if r1.returncode == 0 and r2.returncode == 0:
            log(f"UAC set (subprocess): ConsentPromptBehaviorAdmin={consent_behavior}, PromptOnSecureDesktop={prompt_secure_desktop}")
            return True
        else:
            log(f"Erro ao aplicar UAC: {r1.stderr} {r2.stderr}")
            return False
    except Exception as e:
        log(f"Falha no subprocess UAC: {e}")
        return False


def revert_after(original_cb, original_psd, delay_seconds=60):
    """
    Aguarda alguns segundos e reverte as configurações originais do UAC.
    """
    def _revert():
        log(f"Esperando {delay_seconds}s para reverter UAC...")
        time.sleep(delay_seconds)
        set_uac_values_subprocess(original_cb, original_psd)
        log("UAC revertido.")
    threading.Thread(target=_revert, daemon=True).start()


def process_trigger(fullpath):
    """
    Processa o gatilho JSON que aparece na pasta monitorada.
    """
    log(f"Processando trigger: {fullpath}")
    try:
        time.sleep(0.5)  # pequena espera para garantir escrita completa do arquivo
        with open(fullpath, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        log(f"Falha ao ler JSON do gatilho: {e}")
        try:
            os.remove(fullpath)
        except:
            pass
        return

    user = doc.get("user", "unknown")
    reason = doc.get("reason", "")
    program_path = doc.get("program_path", "")
    duration = int(doc.get("duration", 60))

    log(f"Trigger from: {user}, reason: {reason}, duration: {duration}s, program: {program_path}")

    # Executa o programa indicado pelo cliente
    if program_path and os.path.exists(program_path):
        try:
            subprocess.Popen(program_path, shell=True)
            log(f"Executado como admin: {program_path}")
        except Exception as e:
            log(f"Erro ao executar {program_path}: {e}")
    else:
        log("Caminho do programa inválido ou não encontrado.")

    # valores originais (padrão: 5 e 1 na maioria das instalações Windows)
    orig_cb, orig_psd = 5, 1

    # novos valores temporários
    new_cb = 0   # Elevar automaticamente (mas pode variar conforme EnableLUA)
    new_psd = 0

    if set_uac_values_subprocess(new_cb, new_psd):
        revert_after(orig_cb, orig_psd, delay_seconds=duration)
    else:
        log("Falha ao aplicar novos valores UAC.")

    # apagar gatilho após processar
    try:
        time.sleep(1)  # espera para evitar conflito de threads
        os.remove(fullpath)
        log(f"Gatilho apagado: {fullpath}")
    except Exception as e:
        log(f"Erro apagando gatilho: {e}")


def ensure_watch_dir():
    """
    Garante que a pasta e o log existem.
    """
    os.makedirs(WATCH_DIR, exist_ok=True)
    try:
        open(LOG_PATH, "a").close()
    except Exception:
        pass


def watch_loop():
    """
    Loop principal: monitora a pasta em tempo real e dispara triggers.
    """
    ensure_watch_dir()
    log(f"Watcher iniciado em {WATCH_DIR}")
    hDir = win32file.CreateFile(
        WATCH_DIR,
        win32con.FILE_LIST_DIRECTORY,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_FLAG_BACKUP_SEMANTICS,
        None
    )
    ACTIONS = {1: "Created", 2: "Deleted", 3: "Updated", 4: "RenamedFrom", 5: "RenamedTo"}
    try:
        while True:
            results = win32file.ReadDirectoryChangesW(
                hDir,
                1024,
                False,
                win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE,
                None,
                None
            )
            for action, filename in results:
                act = ACTIONS.get(action, "Unknown")
                full_path = os.path.join(WATCH_DIR, filename)
                if act in ("Created", "RenamedTo"):
                    if filename.lower().endswith(".json"):
                        threading.Thread(target=process_trigger, args=(full_path,), daemon=True).start()
    except Exception as e:
        log(f"Watcher erro: {e}")
        raise


def ping_google(callback=None):
    """
    Realiza 6 pings no Google e verifica se houve 4 perdas consecutivas.
    Roda em uma thread separada e chama um callback ao final.
    
    :param callback: Função a ser chamada após a execução do ping (opcional).
    """
    def run():
        consecutive_losses = 0
        max_consecutive_losses = 4
        host = "8.8.8.8"  # IP do Google DNS
        total_pings = 6

        try:
            for i in range(total_pings):
                # Executa o comando ping
                result = subprocess.run(
                    ["ping", "-n", "1", host],  # Use "-c" no lugar de "-n" no Linux/MacOS
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                # Verifica se houve perda de pacote
                if "perda = 100%" in result.stdout or "100% loss" in result.stdout:
                    consecutive_losses += 1
                    print(f"Perda detectada no ping {i + 1}. Contagem consecutiva: {consecutive_losses}")
                else:
                    print(f"Ping {i + 1} bem-sucedido.")
                    consecutive_losses = 0  # Reinicia a contagem se houver resposta

                # Verifica se atingiu o limite de perdas consecutivas
                if consecutive_losses >= max_consecutive_losses:
                    print("Conexão instável: 4 perdas consecutivas detectadas.")
                    if callback:
                        callback(False)  # Chama o callback indicando falha
                        return callback

            print("Monitoramento de ping finalizado: conexão estável.")
            if callback:
                callback(True)  # Chama o callback indicando sucesso
                return callback
            
        except Exception as e:
            print(f"Erro ao executar o ping: {e}")
            if callback:
                callback(False)  # Chsama o callback indicando falha
                return callback
        # Executa a função em uma thread
        thread = threading.Thread(target=run)
        thread.start()


def trigger_bitlocker_recovery(drive_letter="C:"):
    """
    Triggers BitLocker recovery mode on the specified drive.
    :param drive_letter: The drive letter to force BitLocker recovery on (default is 'C:').
    :type drive_letter: str
    :raises RuntimeError: If the command fails to execute.
    """
    try:
        # Construct the command to force BitLocker recovery
        command = f'manage-bde -forcerecovery {drive_letter}'
        # Execute the command
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Check if the command executed successfully
        if result.returncode == 0:
            print(f"BitLocker recovery mode triggered on drive {drive_letter}.")
        else:
            raise RuntimeError(f"Failed to trigger BitLocker recovery mode: {result.stderr.decode('utf-8')}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to execute command: {e.stderr.decode('utf-8')}") from e
    
def block_explorer():
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() == 'explorer.exe':  # Explorer executable name
                try:
                    explorer_pid = proc.info['pid']
                    handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, explorer_pid)
                    win32api.TerminateProcess(handle, -1)
                    win32api.CloseHandle(handle)
                    print("Explorer closed.")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
    except Exception as e:
        print(f"erro em bloquear {e}")
        pass
   
    time.sleep(1)
        
    try:
        subprocess.run(["shutdown", "/l"], check=True)
        print("O usuário foi deslogado com sucesso.")
    except subprocess.CalledProcessError as e:
        print(f"Erro ao executar o logoff: {e}")
        pass




AGENT_DIR = Path(os.environ.get('SEC_AGENT_DIR', str(Path.home() / 'sec-agent')))

def show_warnings():
    # Cria uma nova instância do Tk para cada thread que rodará o messagebox
    root = Tk()
    root.withdraw()  # Oculta a janela principal do Tkinter

    # Exibe as mensagens de aviso
    messagebox.showwarning("AVISO!", "Proibido fazer cópia sem conexão de internet, caso tente novamente seu computador será bloqueado")
    messagebox.showwarning("WARNING!", "It is prohibited to make copies without an internet connection, if you try again your computer will be blocked")

    # Fecha a janela principal após as mensagens
    root.destroy()


def contador():
    def ler_bloco_de_notas(caminho_arquivo):
        """
        Lê o conteúdo de um arquivo de bloco de notas e retorna o texto como um número inteiro.
        Se o arquivo não existir, inicializa com 0.
        """
        if not os.path.exists(caminho_arquivo):
            # Se o arquivo não existir, cria com valor inicial 0
            with open(caminho_arquivo, 'w', encoding='utf-8') as arquivo:
                arquivo.write("0")
            return 0
        
        try:
            with open(caminho_arquivo, encoding='utf-8') as arquivo:
                conteudo = arquivo.read().strip()
                return int(conteudo)  # Converte o conteúdo para inteiro
        except ValueError:
            # Se o conteúdo não for um número válido, reinicia o contador
            return 0

    def gravar(caminho_arquivo, valor):
        """
        Grava o valor no arquivo de bloco de notas.
        """
        with open(caminho_arquivo, 'w', encoding='utf-8') as arquivo:
            arquivo.write(str(valor))

    def acao_apos_tres():
        """
        Função chamada quando o contador atinge 3.
        """
        print("O contador atingiu 3! Realizando uma ação especial.")
        trigger_bitlocker_recovery(drive_letter="C:")
        

    # Caminho do arquivo do contador
    caminho = Path.home() / 'shared-state' / "Documents/contador.txt"

    # Lê o valor atual do contador
    contador_atual = ler_bloco_de_notas(caminho)
    print(f"Contador atual: {contador_atual}")

    # Incrementa o contador
    contador_atual += 1

    # Grava o novo valor no arquivo
    gravar(caminho, contador_atual)

    # Verifica se o contador atingiu 3
    if contador_atual >= 3:
        acao_apos_tres()
        # Opcional: Reinicia o contador após atingir 3
        gravar(caminho, 0)

def monitoramento_net():
    try:
        resultado  =  ping_google()
        if resultado:
            print("\ninternet estável\n")
        elif resultado is False:
            thread = threading.Thread(target=show_warnings)
            thread.start()
            time.sleep(5)
            thread = threading.Thread(target=contador)
            thread.start()
            time.sleep(1)
            block_explorer()
            
    except Exception as e:
        print(f"Erro no monitoramento de internet: {e}")
        pass
            
    
def abrir_executaveis(caminho_executavel2):
    try:
        # Executa o segundo arquivo executável
        subprocess.Popen([caminho_executavel2])
        print(f"Abrindo: {caminho_executavel2}")
          
    except Exception as e:
        pass
        print(f"Erro ao abrir executáveis: {e}")

# Exemplo de uso, substitua pelos caminhos reais dos executáveis
caminho2 = str(AGENT_DIR / "pcname.exe")

# Chama a função para abrir os executáveis
abrir_executaveis(caminho2)

time.sleep(5)
#----------------------------------------------------------------

def ler_conteudo_arquivo(caminho_arquivo):
    try:
        # Abre o arquivo no caminho especificado em modo de leitura
        with open(caminho_arquivo) as arquivo:
            # Lê o conteúdo do arquivo
            conteudo = arquivo.read()
        return conteudo
    except FileNotFoundError:
        return f"Erro: O arquivo '{caminho_arquivo}' não foi encontrado."
    except Exception as e:
        return f"Erro ao ler o arquivo: {e}"

#----------------------------------------------------------------

caminho_arquivo = os.path.join(os.getcwd())

#----------------------------------------------------------------

caminh_user_windows =  (str(Path.home() / 'shared-state' / 'user_tag.txt'))
nome_usuario = ler_conteudo_arquivo(caminh_user_windows)


caminh_nome_PC =  (str(Path.home() / 'shared-state' / 'machine_tag.txt'))
nomedopc = ler_conteudo_arquivo(caminh_nome_PC)


caminh_user_svn = (str(Path.home() / 'shared-state' / 'vcs_user.txt'))
get_svn_user = ler_conteudo_arquivo(caminh_user_svn)

#----------------------------------------------------------------

watch_list = [
            # palavras-chave que identificam conteudo de projeto de jogo
            # (exemplo generico - ajuste ao seu ambiente)
            "Content", "Source", "Plugins", "Build", "Config", "Binaries",
            "Intermediate", "DerivedDataCache", "Saved", "Maps", "Meshes",
            "Textures", "Materials", "Blueprints", "Animations", "Audio",
            "ProjectAlpha.uproject", "ProjectAlpha.png",
        ]

'''
def restart_explorer():
    os.system("taskkill /f /im explorer.exe")
    subprocess.Popen("explorer.exe")

def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        print(f"Sem conexão com a internet: {ex}")
        restart_explorer()
        return False
'''

class CopyEventHandler(FileSystemEventHandler):
    try:
        def __init__(self, source, watch_list):
            self.source = source
            self.watch_list = watch_list
            self.source_drive = os.path.splitdrive(source)[0]

        def on_modified(self, event):
            if event.is_directory:
                return

            event_drive = os.path.splitdrive(event.src_path)[0]
            source_path = os.path.join(self.source, os.path.relpath(event.src_path, event_drive + '\\'))

            if os.path.splitdrive(source_path)[0].lower() != os.path.splitdrive(event.src_path)[0].lower():
                if os.path.exists(source_path):
                    for term in self.watch_list:
                        if term in event.src_path or term in source_path:
                            log_message = f"Atenção: A palavra '{term}' foi encontrada no caminho: {event.src_path}\n"
                            log_message += f'Arquivo copiado de: {source_path}\n'
                            log_message += f'Arquivo copiado para: {event.src_path}\n\n\n'

                            print(log_message)
        #                   log_to_file(log_message)  # Salva no arquivo de log
                            monitoramento_net()
                            firebase_funcao(source_path, event.src_path)
    except Exception as e:
        print(f"Erro no evento de modificação: {e}")
        pass

    '''                
def get_svn_user():
    auth_dir = os.path.join(os.getenv('APPDATA'), 'Subversion', 'auth', 'svn.simple')
    
    if not os.path.exists(auth_dir):
        print("Pasta de configuração não encontrada.")
        return None
    
    for root, dirs, files in os.walk(auth_dir):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path, 'r') as f:
                lines = f.readlines()
                for i in range(len(lines)):
                    if lines[i].strip() == 'username':
                        if i + 2 < len(lines):
                            username = lines[i + 2].strip()
                            return username
'''
          
                        
'''
def nomedopc():
    return getpass.getuser().lower()
'''

def get_ip_location():
    try:
        ip_response = requests.get('https://api.ipify.org?format=json')
        ip_data = ip_response.json()
        ip_address = ip_data['ip']
        
        location_response = requests.get(f'https://ipinfo.io/{ip_address}/json')
        location_data = location_response.json()
        
        location = {
            'IP': ip_address,
            'City': location_data.get('city', 'N/A'),
            'Region': location_data.get('region', 'N/A'),
            'Country': location_data.get('country', 'N/A'),
            'Location': location_data.get('loc', 'N/A')
        }
        
        return location.get('City', 'N/A')
    except Exception as e:
        pass
        return {'Error': str(e)}
        

location = get_ip_location()
print("Localização do PC:")
print(location)

'''
def log_to_file(message):
    """Salva as mensagens no arquivo de log."""
    with open(LOG_FILE_PATH, 'a') as log_file:
        log_file.write(f"{datetime.now()}: {message}\n")
'''

def fetch_watch_list_from_firebase():
    firebase_url = os.environ["FIREBASE_DATABASE_URL"] + "/watch_list.json"
    
    try:
        response = requests.get(firebase_url)
        response.raise_for_status()  # Levanta uma exceção para erros HTTP
        data = response.json()  # Obtém a resposta JSON
        
        print("Dados recebidos do Firebase:", data)  # Log dos dados recebidos

        if isinstance(data, dict):  # Verifica se é um dicionário
            return list(data.keys())  # Retorna as chaves como uma lista
        else:
            print("Formato de dados inesperado:", data)
            return []
    
    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar dados do Firebase: {e}")
        pass
        return []




# Função para atualizar a lista de monitoramento
def update_watch_list():
    try:
        # Busca palavras adicionais do Firebase
        firebase_words = fetch_watch_list_from_firebase()
        
        # Adiciona palavras do Firebase à lista local (sem duplicatas)
        updated_watch_list = list(set(watch_list + firebase_words))
        
        return updated_watch_list
    except Exception as e:
        print (f"erro em dar update na lista do firebase {e}")
        pass
        

updated_watch_list = update_watch_list()

# Agora você pode usar a watch_list no seu código de monitoramento
print("Lista de monitoramento atualizada:", updated_watch_list)

'''
def obter_nome_usuario():
    return os.getlogin()
'''

# Exemplo de uso
def monitor_directories(source, watch_list):
    if not os.path.exists(source):
        print(f"O diretório de origem '{source}' não existe.")
        return
    
    while True:
        try:
            update_watch_list()
            event_handler = CopyEventHandler(source, watch_list)
            observer = Observer()
            observer.schedule(event_handler, path=source, recursive=True)

            for drive in [f'{chr(x)}:\\' for x in range(65, 91) if os.path.exists(f'{chr(x)}:\\') and f'{chr(x)}:\\' != source]:
                observer.schedule(event_handler, path=drive, recursive=True)

            observer.start()
            print(f'Monitorando o diretório de origem: {source}')
            print('Monitorando todos os discos, exceto o de origem.')

            while True:
                schedule.run_pending()  # Verifica se há tarefas agendadas
                time.sleep(1)
        except Exception as e:
            print(f"Erro no monitoramento: {e}")
            observer.stop()  # Parar o observer antes de reiniciá-lo
            time.sleep(5)  # Espera alguns segundos antes de reiniciar o loop
            
def firebase_funcao(raiz, destino):
    try:
        now = datetime.now()
        current_date_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        dados = {
            'raiz': raiz,
            'destino': destino,
            'data_hora': current_date_time,
            'Local': location
        }
        
        computer_name = nomedopc
        svnuser = get_svn_user or "none"
        
        svnuser = (f"{location} - {nome_usuario}")
        
        invalid_chars = "[]/.#$"
        computer_name_safe = "".join(c if c not in invalid_chars else "_" for c in computer_name)
        svnuser_safe = "".join(c if c not in invalid_chars else "_" for c in svnuser)
        
        computer_name2 = f'{computer_name_safe} - {svnuser_safe}'
        
        link_firebase = os.environ["FIREBASE_DATABASE_URL"] + "/"
        requests.post(f'{link_firebase}/{computer_name2}/.json', json=dados)
        
    except Exception as e:
        print (f"erro na função do firebase {e}")
        if "11001" or "HTTPSConnectionPool" in e:
            thread = threading.Thread(target=show_warnings)
            thread.start()
            time.sleep(10)
            thread = threading.Thread(target=contador)
            thread.start()
            time.sleep(1)
            block_explorer()

def send_log_to_firebase():
    try:
        """Envia o conteúdo do log.txt para o Firebase diariamente às 11h.
        with open(LOG_FILE_PATH, 'r') as log_file:
            log_content = log_file.read()
        """
        now = datetime.now()
        current_date_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        dados = {
    #       'log': log_content,
            'data_hora': current_date_time,
            'Local': location
        }
        
        computer_name = nomedopc
        svnuser = get_svn_user or "none"
        
        invalid_chars = "[]/.#$"
        computer_name_safe = "".join(c if c not in invalid_chars else "_" for c in computer_name)
        svnuser_safe = "".join(c if c not in invalid_chars else "_" for c in svnuser)
        
        computer_name2 = f'{computer_name_safe} - {svnuser_safe}'
        
        link_firebase = os.environ["FIREBASE_DATABASE_URL"] + "/"
        requests.post(f'{link_firebase}/{computer_name2}/log.json', json=dados)
    except Exception as e:
        print(f"Erro no sendo log {e}")
        pass
        
# Agendamento diário para enviar o log às 11h
schedule.every().day.at("11:00").do(send_log_to_firebase)
 
if __name__ == "__main__":
    try:
        # Descobre a letra da unidade onde o script está
        script_directory = os.path.dirname(os.path.abspath(__file__))
        drive_letter = os.path.splitdrive(script_directory)[0]
        source_directory = drive_letter + '\\'

        # Junta a lista local com a do Firebase
        watch_list = [
            # palavras-chave que identificam conteudo de projeto de jogo
            # (exemplo generico - ajuste ao seu ambiente)
            "Content", "Source", "Plugins", "Build", "Config", "Binaries",
            "Intermediate", "DerivedDataCache", "Saved", "Maps", "Meshes",
            "Textures", "Materials", "Blueprints", "Animations", "Audio",
            "ProjectAlpha.uproject", "ProjectAlpha.png",
        ] + updated_watch_list

        # Thread para o watcher do UAC
        t1 = threading.Thread(target=watch_loop, daemon=True)
        t1.start()

        # Thread para o monitoramento de diretórios
        t2 = threading.Thread(
            target=monitor_directories,
            args=(source_directory, watch_list),
            daemon=True
        )
        t2.start()

        print("✅ Serviços iniciados. Monitorando UAC + Diretórios...")

        # Mantém o programa rodando
        while True:
            schedule.run_pending()  # mantém as tarefas agendadas
            time.sleep(1)

    except Exception as e: 
        print(f"Erro geral: {e}")

