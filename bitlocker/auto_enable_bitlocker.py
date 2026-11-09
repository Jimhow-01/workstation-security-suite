import ctypes
import getpass
import logging
import os
import socket
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import psutil
import pyautogui
import requests
import win32api
import win32con
import win32gui
import win32ts
import wmi
from pynput import keyboard
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from win32api import GetModuleHandle

pyautogui.FAILSAFE = False

# Secret key for HMAC
SECRET_KEY = os.environ["HMAC_SECRET"].encode()
# Windows constants for session change notifications
WTS_SESSION_UNLOCK = 8
WTS_SESSION_LOCK = 7
WM_WTSSESSION_CHANGE = 0x02B1

# Timing thresholds
SHUTDOWN_THRESHOLD = 10 
INTERNET_POLL_SECONDS = 60


# Configuração do logging
logging.basicConfig(
    filename=str(Path.cwd() / 'agent.log'),  # Caminho completo para o arquivo de log
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Função para redirecionar stdout e stderr para o log
class StreamToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        if message.strip() != "":
            self.logger.log(self.level, message.strip())

    def flush(self):
        pass

# Redirecionar stdout e stderr para o log
#sys.stdout = StreamToLogger(logging.getLogger(), logging.INFO)
#sys.stderr = StreamToLogger(logging.getLogger(), logging.ERROR)

# Exemplo de mensagens de log e saída no terminal
print('Isso será capturado no log como INFO')
logging.info('Iniciando o processo')

try:
    # Simulação de código
    resultado = 10 / 2
    print(f'Resultado: {resultado}')  # Isso será capturado no log
except ZeroDivisionError as e:
    logging.error(f'Erro ocorreu: {e}')
    print(f'Erro ocorreu: {e}')  # Também será capturado no log

logging.info('Processo finalizado')
print('Processo finalizado no terminal')

drive_letter = "C:"

root = tk.Tk()

recovery_key_path = os.environ.get("RECOVERY_KEY_DIR", str(Path.home() / "recovery-keys"))

drive_letter = "C:"

import re
from random import randint

# Dominio de e-mail corporativo aceito na tela de desbloqueio
COMPANY_EMAIL_DOMAIN = os.environ.get('COMPANY_EMAIL_DOMAIN', '@example.com')


# Diretorio de implantacao do agente na estacao
AGENT_DIR = Path(os.environ.get('SEC_AGENT_DIR', str(Path(os.environ.get('PROGRAMDATA', '.')) / 'sec-agent')))

# Conta padrao criada no provisioning da estacao
DEFAULT_ACCOUNT = "workstation-default"

# Verifica se o TPM está ativado e mostra popup se não estiver
def checar_tpm_e_popup():
    try:
        c = wmi.WMI()
        for bios in c.Win32_BIOS():
            print(f"Fabricante BIOS: {bios.Manufacturer}")
            Fabricante_Bios = {bios.Manufacturer}
            print(f"Versão BIOS: {bios.SMBIOSBIOSVersion}")
            Versao_Bios = {bios.SMBIOSBIOSVersion}
            print(f"Data de lançamento: {bios.ReleaseDate}")
            Data_de_lancamento = {bios.ReleaseDate}
            
        for board in c.Win32_BaseBoard():
            print(f"Fabricante Placa-mãe: {board.Manufacturer}")
            Fabricante_Placa = {board.Manufacturer}
            print(f"Modelo Placa-mãe: {board.Product}")
            Modelo_PLaca = {board.Product}
    except Exception as e:
        print(f"Erro ao obter informações: {e}")
    
    # Chama o PowerShell para obter o status do TPM em formato lista
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "Get-Tpm | Format-List TpmPresent,TpmReady,TpmEnabled"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout

    # Extrai o valor de TpmEnabled (True/False)
    m = re.search(r"TpmEnabled\s*:\s*(True|False)", output)
    tpm_enabled = (m and m.group(1) == "True")

    # Se TPM não ativado, mostra popup de aviso
    if not tpm_enabled:
        ctypes.windll.user32.MessageBoxW(
            None,
            "TPM não está ativado ou pronto para uso!\n\n" +
            "1: Certifique-se que o TPM(trusted platform module) ou PTT está ativado na BIOS.\n"
            "Qualquer dúvida, entre em contato com o suporte tecnico interno.\n",
            f"Aviso de TPM\n Informações da placa mãe:\n Fabricante da Bios: {Fabricante_Bios}\nVersão da bios:{Versao_Bios}\nData de lançamento:{Data_de_lancamento}\nFabricante da Placa:{Fabricante_Placa}\nModelo da placa:{Modelo_PLaca}",
            0x40  # MB_ICONINFORMATION
        )
        time.sleep(300)  # Espera 3 minutos antes de reiniciar o sistema
        restart_system()

    return tpm_enabled

def _http_probe_204(timeout_seconds: int = 5) -> bool:
    """
    HTTP probe that expects a 204/No Content from well-known endpoints.
    Returns True if any endpoint gives the expected status code.

    :param timeout_seconds: Timeout per request in seconds.
    :type timeout_seconds: int
    :rtype: bool
    """
    urls = [
        "https://www.gstatic.com/generate_204",          # Google (HTTPS)
        "http://connectivitycheck.gstatic.com/generate_204",  # Google (HTTP)
        "http://www.msftconnecttest.com/connecttest.txt",     # Microsoft (expects 200)
    ]
    try:
        for url in urls:
            try:
                resp = requests.get(url, timeout=timeout_seconds, allow_redirects=False)
                if "generate_204" in url and resp.status_code == 204:
                    return True
                if "connecttest.txt" in url and resp.status_code == 200:
                    return True
            except requests.RequestException:
                continue
    except Exception:
        pass
    return False


def _tcp_probe(endpoints: list[tuple[str, int]] | None = None, timeout_seconds: int = 3) -> bool:
    """
    TCP connectivity probe to public IPs (no DNS needed).
    Returns True if any socket connects.

    :param endpoints: List of (host, port) tuples to try.
    :type endpoints: list[tuple[str, int]] | None
    :param timeout_seconds: Timeout per socket in seconds.
    :type timeout_seconds: int
    :rtype: bool
    """
    if endpoints is None:
        endpoints = [
            ("1.1.1.1", 443),
            ("8.8.8.8", 53),
            ("8.8.4.4", 53),
            ("9.9.9.9", 443),
        ]
    for host, port in endpoints:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            continue
    return False


def _dns_probe(hosts: list[str] | None = None) -> bool:
    """
    DNS resolution probe.
    Returns True if we can resolve at least one common hostname.

    :param hosts: Hostnames to resolve.
    :type hosts: list[str] | None
    :rtype: bool
    """
    if hosts is None:
        hosts = ["www.microsoft.com", "www.google.com", "www.cloudflare.com"]
    for h in hosts:
        try:
            socket.gethostbyname(h)
            return True
        except OSError:
            continue
    return False


def check_internet(timeout_seconds: int = 5) -> bool:
    """
    Robust connectivity check combining HTTP-204, TCP, and DNS probes.
    Consider ONLINE only if at least 2 of the 3 categories succeed.

    :param timeout_seconds: Probe timeout in seconds (per probe).
    :type timeout_seconds: int
    :return: True if considered online; False otherwise.
    :rtype: bool
    """
    http_ok = _http_probe_204(timeout_seconds)
    tcp_ok = _tcp_probe(timeout_seconds=timeout_seconds)
    dns_ok = _dns_probe()

    ok_count = sum((1 if http_ok else 0, 1 if tcp_ok else 0, 1 if dns_ok else 0))
    return ok_count >= 2


def monitor_internet(poll_seconds: int = INTERNET_POLL_SECONDS) -> None:
    """
    Monitor connectivity and restart if needed.
    """
    global SHUTDOWN_THRESHOLD


    while True:
        if not check_internet():
            SHUTDOWN_THRESHOLD -= 1
            if SHUTDOWN_THRESHOLD <= 0:
                subprocess.run(["shutdown", "/r", "/t", str(0)])
        else:
            SHUTDOWN_THRESHOLD = 10  # Reset threshold when online
            
        time.sleep(max(5, int(poll_seconds)))


def start_internet_monitor_thread() -> None:
    """
    Start the internet monitor on a daemon thread.
    """
    t = threading.Thread(target=monitor_internet, daemon=True)
    t.start()
    

def logoff_usuario():
    """
    Faz logoff do usuário atual no Windows.
    """
    try:
        subprocess.run(["shutdown", "/l"], check=True)
        print("✅ O usuário foi deslogado com sucesso.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao tentar deslogar: {e}")

# Renomeia o "System Product Name" para um nome aleatório
def renomear_system_product_name():
    aleatorio1 = (randint(0,100000))  
    aleatorio2 = (randint(0,500))

    full = (f"{aleatorio1}") + (f"{aleatorio2}")
    print (full)
    
    # Obtém o nome do usuário atual
    nome_usuario = (f"WS{full}")

    # Comando PowerShell para renomear o "System Product Name"
    comando_powershell = f'Rename-Computer -NewName "{nome_usuario}" -Force -PassThru'

    try:
        # Executa o comando PowerShell para renomear o computador
        subprocess.run(["powershell", "-Command", comando_powershell], check=True)
        print(f"Nome do computador renomeado para: {nome_usuario}")
    except subprocess.CalledProcessError as e:
        print(f"Erro ao renomear o computador: {e}")

# Altera a notificação de UAC para o nível padrão
def alterarnotficacao():

    # Comando para remover o usuário do grupo de administradores
    comando_remover_admin = r'reg.exe ADD HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System /v ConsentPromptBehaviorAdmin /t REG_DWORD /d 1 /f'
    resultado = subprocess.run(comando_remover_admin, shell=True, capture_output=True, text=True)

    if resultado.returncode == 0:
        print('O comando de notficação foi feito com sucesso')
    else:
        print('Deu erro para alterar a notificação')
        return
    print(resultado)

# Exclui o disco X completamente
def delete_drive_x():
    """Exclui completamente o disco com a letra X usando o diskpart."""
    script_content = """
    select volume X
    delete volume override
    """
    
    script_path = r"delete_drive_script.txt"
    
    try:
        # Salva o script temporariamente
        with open(script_path, "w") as f:
            f.write(script_content)

        # Verifica se o arquivo de script foi criado corretamente
        if not os.path.exists(script_path):
            raise FileNotFoundError("O script para excluir o volume não foi criado corretamente.")

        # Executa o diskpart com o script
        result = subprocess.run(["diskpart", "/s", script_path], check=True, capture_output=True, text=True)

        print("Disco X excluído com sucesso.")
        print(result.stdout)

    except FileNotFoundError as fnf_error:
        print(f"Erro: {fnf_error}")
        
    except subprocess.CalledProcessError as e:
        print(f"Erro ao excluir o disco X (code: {e.returncode}):")
        print(f"Saída de erro (stderr): {e.stderr.strip()}")
        print(f"Saída padrão (stdout): {e.stdout.strip()}")
        
    except Exception as ex:
        print(f"Ocorreu um erro inesperado: {ex}")

    finally:
        # Remove o arquivo de script temporário após a execução
        if os.path.exists(script_path):
            os.remove(script_path)

#remove o adm do usuario
def remover_admin(usuario):
    try:
        # Comando para remover o usuário do grupo de administradores
        comando_remover_admin = f'net localgroup Administrators "{usuario}" /delete'
        resultado = subprocess.run(comando_remover_admin, shell=True, capture_output=True, text=True)

        if resultado.returncode == 0:
            print(f'O usuário {usuario} foi removido do grupo de Administradores.')
        else:
            print(f'Erro ao remover o usuário {usuario}: {resultado.stderr}')
            return

        # Adicionando o usuário ao grupo de usuários padrão
        comando_adicionar_padrao = f'net localgroup Users "{usuario}" /add'
        resultado = subprocess.run(comando_adicionar_padrao, shell=True, capture_output=True, text=True)

        if resultado.returncode == 0:
            print(f'O usuário {usuario} foi adicionado ao grupo de Usuários comuns.')
        else:
            print(f'Erro ao adicionar o usuário {usuario} ao grupo de Usuários comuns: {resultado.stderr}')
    except Exception as e:
        print(f'Ocorreu um erro: {e}')

# Função para excluir o arquivo especificado
def delete_file(file_path):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Arquivo excluído: {file_path}")
            else:
                print(f"Arquivo não encontrado: {file_path}")
        except Exception as e:
            print(f"Erro ao excluir o arquivo: {e}")

#reinicia o pc
def restart_system():
    """Restart the system to run the BitLocker hardware test."""
    subprocess.run(["shutdown", "/r", "/t", "0"], check=True)

#mostra a imagem com a plavra "OK!"
def alerta():
    # Configurações da janela principal
    root = tk.Tk()
    root.title("Workstation Locked")

    # Tela cheia
    root.attributes('-fullscreen', True)

    # Define cor de fundo (verde claro)
    root.configure(bg="lightgreen")

    # Mensagem de bloqueio
    large_message = tk.Label(
        root,
        text="\n\n\n\nBitlocker finalizado, clique em 'OK'\n"
             "Clicando em 'OK', o Windows irá reiniciar,\n"
             "após isso pode ser usado normalmente.",
        font=("Helvetica", 18),
        justify="center",
        bg="lightgreen"   # Fundo igual ao da janela
    )
    large_message.pack(pady=20)

    # Função do botão
    def on_ok():
        # Reinicia o Windows
        os.system("shutdown /r /t 0")
        # ou só fecha a janela:
        # root.destroy()

    # Botão centralizado
    ok_button = tk.Button(
        root,
        text="OK",
        font=("Helvetica", 16),
        width=10,
        command=on_ok
    )
    ok_button.pack(pady=50)

    # Execução da aplicação
    root.mainloop()
    
#bloqueia o gerenciador de tarefas
def block_task_manager():
    for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() == 'taskmgr.exe':  # Task Manager executable name
                try:
                    task_manager_pid = proc.info['pid']
                    handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, task_manager_pid)
                    win32api.TerminateProcess(handle, -1)  # Force terminate Task Manager
                    win32api.CloseHandle(handle)
                    print("Task Manager closed.")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
    root.after(1000, block_task_manager)  # Repeat the check every second

#verifica o nome atual
def verificar_nomeatual2():
    # Obtém o nome do usuário atual
    usuario_atual = getpass.getuser().lower()

    # Verifica se o usuario ainda e a conta padrao da estacao
    if usuario_atual == DEFAULT_ACCOUNT:
        print(f"O nome do usuario ainda e '{DEFAULT_ACCOUNT}'.")

    else:
        print(f"O nome do usuario nao e '{DEFAULT_ACCOUNT}', e '{usuario_atual}'.")
        return usuario_atual

#Envia as informações pro Firebase
def enviar_para_firebase(recovery_key_path):
    try:
        comando_listar = 'Get-LocalUser | Select-Object -ExpandProperty Name'
        resultado = subprocess.run(
            ["powershell", "-Command", comando_listar],
            capture_output=True,
            text=True
        )

        if resultado.returncode == 0 and resultado.stdout.strip():
            usuarios = resultado.stdout.strip().splitlines()
        else:
            print("Nenhum usuário encontrado.")
    except Exception as erro:
        print(f"Erro ao listar usuários: {erro}")

    usuarios_filtrados = [usuario for usuario in usuarios if usuario.lower() != 'administrator' and usuario.lower() != 'administrador']


    # Imprimir os usuários filtrados
    if usuarios_filtrados:
        print("Usuários filtrados:", usuarios_filtrados)
    else:
        print("Nenhum usuário diferente de 'Administrator' encontrado.")
    
    # NOTE: a chave de recuperacao e publicada em TEXTO CLARO no Realtime Database.
    # Quem tem acesso a esta base consegue descriptografar qualquer disco da frota.
    # Correto: cifrar antes de publicar, ou publicar so um identificador e guardar a
    # chave em cofre com controle de acesso e auditoria.
    firebase_url = os.environ["FIREBASE_DATABASE_URL"] + "/recovery_keys.json"
    
    # Conteúdo a ser enviado
    recovery_data = {
        "Nome:" : user2,
        "recovery_key": recovery_key_path,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")  # Data e hora atuais
    }

    # Envia uma solicitação POST para o Firebase
    try:
        response = requests.post(firebase_url, json=recovery_data)
        if response.status_code == 200:
            print(f"Chave de recuperação enviada ao Firebase com sucesso: {response.json()}")
        else:
            print(f"Falha ao enviar a chave ao Firebase. Status: {response.status_code}")
    except Exception as e:
        print(f"Erro ao enviar a chave para o Firebase: {e}")

#Configura o remote
def configurar_remote():
    resultado_remote = "Chrome remote desktop falhou"
    try:
        def verificar_chrome_aberto():
            for proc in psutil.process_iter():
                if 'chrome.exe' in proc.name():
                    return True
            return False

        if verificar_chrome_aberto():
            subprocess.run(["taskkill", "/f", "/im", "chrome.exe"])
            time.sleep(1)

        servico = Service(ChromeDriverManager().install()) 
        opcoes = Options()
        
        import win32con
        import win32gui

        hwnd = win32gui.FindWindow(None, "Google Chrome")
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)  # Esconde a janela
        opcoes.add_argument("--start-minimized")
        #opcoes.add_argument("--headless=new")

        navegador = webdriver.Chrome(service=servico, options=opcoes)
        navegador.set_window_position(-5000, 0)

        print("Realizando login no site do remote desktop...")
        navegador.get("https://remotedesktop.google.com/access")
        time.sleep(3)
        navegador.find_element(By.XPATH, "//input[@aria-label='E-mail ou telefone']").send_keys(os.environ["SERVICE_ACCOUNT_EMAIL"])
        time.sleep(1)
        navegador.find_element(By.XPATH, "//span[text()='Avançar']").click()
        time.sleep(3)
        navegador.find_element(By.XPATH, "//input[@aria-label='Digite sua senha']").send_keys(os.environ["SERVICE_ACCOUNT_PASSWORD"])
        time.sleep(1)
        navegador.find_element(By.XPATH, "//span[text()='Avançar']").click()
        time.sleep(2)
        print("Configurando a máquina no remote desktop...")
        time.sleep(10)
        navegador.find_element(By.XPATH, "//span[text()='Set up via SSH']").click()
        print("Clicou no set up via ssh")
        time.sleep(3)
        navegador.find_element(By.XPATH, "//span[text()='Begin']/ancestor::div[@role='button']").click()
        print("Clicou no begin")
        time.sleep(3)

        wait = WebDriverWait(navegador, 20)

        time.sleep(3)

        botoes_next = navegador.find_elements(By.XPATH, "//div[@role='button' and @aria-label='Next']")

        botao_clicado = False
        for botao in botoes_next:
            texto = botao.text.strip()
            if texto == "Next":
                try:
                    navegador.execute_script("arguments[0].scrollIntoView();", botao)
                    navegador.execute_script("arguments[0].click();", botao)
                    print("Clicou no botão Next com texto visível")
                    botao_clicado = True
                    break
                except Exception as e:
                    print("Erro ao clicar no botão Next:", e)

        if not botao_clicado:
            print("Nenhum botão Next com texto visível foi clicado")
            raise Exception("Falha ao clicar no botão Next")
        
        try:
            print("Aguardando botão 'Authorize' aparecer...")
            authorize_btn = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//span[text()='Authorize']/ancestor::div[@role='button']"
            )))
            authorize_btn.click()
            print("Clicou no authorize")
        except Exception as e:
            print("Falha ao clicar no botão Authorize:", e)
            raise
        
        
        time.sleep(10)
        textarea_element = navegador.find_element(By.XPATH, "//textarea[@aria-label='Windows (PowerShell)']")
        conteudo_textarea = textarea_element.get_attribute("value")
        print("Conteúdo da textarea:", conteudo_textarea)

        pin = os.environ.get("CHROME_RD_PIN", input("Chrome Remote Desktop PIN: ").strip())
        usuario_windows = os.getlogin()

        print("Executando comando PowerShell para setar a máquina...")
        time.sleep(3)

        comando_powershell = f'& "${{Env:PROGRAMFILES(X86)}}\\Google\\Chrome Remote Desktop\\CurrentVersion\\remoting_start_host.exe" --code="{conteudo_textarea.split("--code=")[1].split(" --redirect-url")[0]}" --redirect-url="https://remotedesktop.google.com/_/oauthredirect" --name="{usuario_windows}" --pin="{pin}"'
        
        try:
            subprocess.run(["powershell", "-Command", comando_powershell], shell=True)
            print("Comando PowerShell executado com sucesso, fechando tudo...")
            resultado_remote = "Chrome remote desktop configurado com sucesso"
            time.sleep(3)
            
        except Exception as e:
            resultado_remote = "Chrome remote desktop falhou"
            print("Erro ao executar o comando PowerShell:", e)
        finally:
            navegador.quit()  
        time.sleep(10)              
        
        # Caminho do perfil padrão do Chrome
        perfil_chrome = str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")

        try:
            # Verifica se o diretório existe e apaga
            if os.path.exists(perfil_chrome):
                print(f"Apagando o perfil 'Default' do Chrome em: {perfil_chrome}")
                import shutil
                shutil.rmtree(perfil_chrome, ignore_errors=True)
                print("Perfil 'Default' apagado com sucesso.")
            else:
                print("Perfil 'Default' não encontrado. Nada foi apagado.")
        except Exception as e:
            print(f"Erro ao apagar o perfil 'Default': {e}")
        return resultado_remote
    
    except Exception as e:
        print(f"{resultado_remote}")
        return resultado_remote


#mostra o status do bitlock com porcentagem
def check_bitlocker_status(drive_letter):
    """Check if BitLocker is enabled on the given drive."""
    command = f"manage-bde -status {drive_letter}"
    result = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True)
    print (result)
    return "Percentage Encrypted: 100%" in result.stdout

def bloquear_bitlocker():
    try:
        print("\n🔒 Bloqueando ativação do BitLocker em todos os discos, exceto C:...")
        subprocess.run(["reg", "add", "HKLM\\SOFTWARE\\Policies\\Microsoft\\FVE", "/v", "DisableBitLockerOnDrives", "/t", "REG_DWORD", "/d", "1", "/f"], check=True)
        
        print("\n🚫 Removendo políticas que ativam BitLocker automaticamente...")
        subprocess.run(["reg", "delete", "HKLM\\SOFTWARE\\Policies\\Microsoft\\FVE", "/f"], check=True)
        
        # Bloqueia a ativação do BitLocker em discos secundários (exceto C:)
        print("\n🔒 Impedindo BitLocker em discos secundários...")
        subprocess.run(["reg", "add", "HKLM\\SOFTWARE\\Policies\\Microsoft\\FVE", "/v", "RDVDenyWriteAccess", "/t", "REG_DWORD", "/d", "1", "/f"], check=True)
        
        # Desativa manualmente o BitLocker em discos D:, E:, F:, etc.
        letras_disco = ["D:", "E:", "F:", "G:", "H:", "I:", "J:"]  # Adicione mais se necessário
        for drive in letras_disco:
            print(f"\n🚫 Bloqueando BitLocker no {drive} ...")
            subprocess.run(["manage-bde", "-protectors", drive, "-disable"], check=True)
        
        print("\n🔄 Aplicando as políticas para bloquear o BitLocker...")
        subprocess.run(["gpupdate", "/force"], check=True)
        
        print("✅ BitLocker bloqueado com sucesso em todos os discos, exceto C:!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao bloquear o BitLocker: {e}")

#habilita o bitlock
def enable_bitlocker():
    try:
        # 1) Ativa o BitLocker no C:
        cmd_enable = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command",
            "Enable-BitLocker -MountPoint C: "
            "-RecoveryPasswordProtector "
            "-SkipHardwareTest "
            "-UsedSpaceOnly "
            "-EncryptionMethod XtsAes128"
        ]
        subprocess.run(cmd_enable, check=True)

        # 2) Captura a chave de recuperação
        get_recovery_key_cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command",
            "(Get-BitLockerVolume -MountPoint 'C:')"
            ".KeyProtector | "
            "Where-Object {$_.KeyProtectorType -eq 'RecoveryPassword'} | "
            "Select-Object -ExpandProperty RecoveryPassword"
        ]
        recovery_key = subprocess.run(
            get_recovery_key_cmd,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        # 3) Salva no arquivo
        computer_name = os.environ['COMPUTERNAME']
        key_file_name = f"{computer_name}_Bitlocker.txt"
        key_file_path = os.path.join(recovery_key_path, key_file_name)
        with open(key_file_path, 'w') as f:
            f.write(recovery_key)

        # 4) Em vez de subprocess.run([...]), só leia o arquivo:
        with open(key_file_path) as f:
            content = f.read()
        enviar_para_firebase(content)
        print("Chave de recuperação enviada ao Firebase.")

        return True

    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")
        return False
    
#retorna o nome atual
def verificar_nomeatual():
    # Obtém o nome do usuário atual
    usuario_atual = getpass.getuser().lower()

    # Verifica se o usuario ainda e a conta padrao da estacao
    if usuario_atual == DEFAULT_ACCOUNT:
        print(f"O nome do usuario ainda e '{DEFAULT_ACCOUNT}'.")
        return True
    else:
        print(f"O nome do usuario nao e '{DEFAULT_ACCOUNT}', e '{usuario_atual}'.")
        return False
    
#renomeia o usuario
def renomear_usuario():
    def executar_renomear():
        # Função para verificar se o usuário existe
        def verificar_usuario_existe(usuario):
            try:
                comando_verificar = f'Get-LocalUser -Name "{usuario}"'
                print(f"Executando comando para verificar se o usuário existe: {comando_verificar}")
                resultado = subprocess.run(
                    ["powershell", "-Command", comando_verificar],
                    capture_output=True,
                    text=True
                )

                print(f"Resultado da verificação: {resultado.stdout.strip()}")

                return resultado.returncode == 0
            except Exception as erro:
                print(f"Erro ao verificar usuário: {erro}")
                return False

        def renomear_usuario_windows(usuario_atual, novo_nome):
            try:
                comando = f'rename-localuser -name "{usuario_atual}" -newname "{novo_nome}"'
                print(f"Executando comando para renomear usuário: {comando}")
                resultado = subprocess.run(
                    ["powershell", "-Command", comando],
                    check=False,
                    capture_output=True,
                    text=True
                )

                print(f"Resultado da renomeação: {resultado.stdout.strip()}")

                if resultado.returncode == 0:
                    print(f"Sucesso: Usuário renomeado de {usuario_atual} para {novo_nome}.")
                    root.quit()  # Encerra a janela Tkinter
                    restart_system()
                    
                else:
                    print(f"Erro na renomeação: Código de erro: {resultado.returncode}, Mensagem: {resultado.stderr}")

            except Exception as erro:
                messagebox.showerror("Erro", f"Ocorreu um erro inesperado: {erro}")
                print(f"Erro inesperado: {erro}")

        def renomear_usuario():
            novo_nome_email = entry.get().strip()  # Obtém o novo nome do campo de entrada
            usuario_atual = DEFAULT_ACCOUNT  # Nome do usuário que deve ser renomeado
            print(f"Tentando renomear usuário '{usuario_atual}' para '{novo_nome_email}'")

            if not novo_nome_email:
                messagebox.showerror("Erro", "Por favor, digite um novo nome.")
                print("Erro: Novo nome não foi fornecido.")
                return

            # Remove a parte do e-mail após o '@'
            novo_nome = novo_nome_email.split('@')[0]  # Pega apenas a parte antes do '@'

            if not verificar_usuario_existe(usuario_atual):
                messagebox.showerror("Erro", f"O usuário '{usuario_atual}' não existe.")
                print(f"Erro: O usuário '{usuario_atual}' não existe.")
                return
            
            renomear_usuario_windows(usuario_atual, novo_nome)

        renomear_usuario()

    def disconnect_all_monitors():
        try:
            while True:
                # Switch to single display mode using DisplaySwitch.exe
                subprocess.run(["DisplaySwitch.exe", "/internal"], check=True)
                print("Successfully switched to single display mode.")
                
                # Espera antes de forçar novamente
                time.sleep(5)  # Ajuste o tempo de acordo com a necessidade
        except subprocess.CalledProcessError as e:
            print(f"Failed to switch display mode. Error: {e}")
            
    def start_monitor_disconnection():
        monitor_thread = threading.Thread(target=disconnect_all_monitors)
        monitor_thread.daemon = True  # Define a thread como daemon para que ela finalize com o programa principal
        monitor_thread.start()

    def on_ok_click():
        email = entry.get().strip()
        if email.endswith(COMPANY_EMAIL_DOMAIN):
            username = email.split('@')[0]
            executar_renomear()
        else:
            print("Por favor, insira um email válido da empresa.")
            
    def lock_workstation():
        ctypes.windll.user32.LockWorkStation()
        
    def restrict_mouse():
        x1 = frame.winfo_rootx()
        y1 = frame.winfo_rooty()
        x2 = x1 + frame.winfo_width()
        y2 = y1 + frame.winfo_height()

        mouse_x, mouse_y = pyautogui.position()

        # Restrict the mouse only if it goes outside the frame
        if not (x1 <= mouse_x <= x2 and y1 <= mouse_y <= y2):
            safe_margin = 10  # Small margin to keep the mouse inside the frame
            new_x = min(max(mouse_x, x1 + safe_margin), x2 - safe_margin)
            new_y = min(max(mouse_y, y1 + safe_margin), y2 - safe_margin)
            pyautogui.moveTo(new_x, new_y)

        root.after(10, restrict_mouse)
        
 
    def block_task_manager():
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() == 'taskmgr.exe':  # Task Manager executable name
                try:
                    task_manager_pid = proc.info['pid']
                    handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, task_manager_pid)
                    win32api.TerminateProcess(handle, -1)  # Force terminate Task Manager
                    win32api.CloseHandle(handle)
                    print("Task Manager closed.")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

        root.after(1000, block_task_manager)  # Repeat the check every second
        
    def block_explorer():
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() == 'explorer.exe':  # Explorer executable name
                try:
                    explorer_pid = proc.info['pid']
                    handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, explorer_pid)
                    win32api.TerminateProcess(handle, -1)  # Force terminate Explorer
                    win32api.CloseHandle(handle)
                    print("Explorer closed.")
                    #force_shutdown()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

    def block_alt_tab():
        def on_press(key):
            try:
                # Detect if the Alt key is pressed
                if key == keyboard.Key.alt:
                    ctypes.windll.user32.BlockInput(True)  # Bloqueia a entrada do usuário
                    print("Alt key detected, blocking input.")
                    block_explorer()
                elif key == keyboard.Key.tab:
                    # Bloqueia o Alt+Tab
                    ctypes.windll.user32.BlockInput(True)
                    print("Alt+Tab detected, blocking input.")
                    block_explorer()
            except AttributeError:
                pass

        def on_release(key):
            # Desbloqueia a entrada quando as teclas são liberadas
            if key == keyboard.Key.alt or key == keyboard.Key.tab:
                ctypes.windll.user32.BlockInput(False)  # Desbloqueia a entrada do usuário
                print("Input unblocked.")

        '''
        # Inicia o monitoramento do teclado
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
        '''
        
    def start_blocking():
        blocking_thread = threading.Thread(target=block_alt_tab)
        blocking_thread.daemon = True  # Permite que o thread seja encerrado quando o programa fechar
        blocking_thread.start()

    def remove_window_buttons(hwnd):
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style &= ~win32con.WS_SYSMENU
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        win32gui.SetWindowPos(hwnd, None, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)

    def create_session_listener():
        wc = win32gui.WNDCLASS()
        wc.hInstance = GetModuleHandle(None)
        wc.lpszClassName = "SessionChangeListener"
        
        class_atom = win32gui.RegisterClass(wc)
        hwnd = win32gui.CreateWindow(class_atom, "SessionChangeListener", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        
        # Register for session notifications
        win32ts.WTSRegisterSessionNotification(hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
        
        # Start the message loop to listen for session changes
        win32gui.PumpMessages()

    def block_close():
        pass  # Bloqueia o fechamento da janela
    
    
    # Configurações da janela principal
    root = tk.Tk()
    root.title("Workstation Locked")
    root.protocol("WM_DELETE_WINDOW", block_close)

    # Make the window fullscreen
    root.attributes('-fullscreen', True)                             # TODO: UNCOMMENT THIS LINE

    # Make sure the window is always on top
    #root.attributes('-topmost', True)                             # TODO: UNCOMMENT THIS LINE 

    root.update_idletasks()

    # Remove botões de minimizar, maximizar e fechar
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    #remove_window_buttons(hwnd)

    # Mensagem de bloqueio
    large_message = tk.Label(root, text="\n\n\n\nPara criar um novo user, inisira o Email corporativo.", font=("Helvetica", 16))
    large_message.pack(pady=20)

    # Campo de entrada para o email
    frame = tk.Frame(root, borderwidth=2, relief="solid")
    frame.pack(padx=20, pady=20)
    entry = tk.Entry(frame, width=40)
    entry.pack(padx=20, pady=10)
    entry.focus_set()

    # Botão OK
    button = tk.Button(frame, text="OK", command=on_ok_click)
    button.pack(pady=10)

    #restrict_mouse()
    #block_task_manager()
    #block_explorer()
    #start_monitor_disconnection()
    #start_blocking()

    # Execução da aplicação
    root.mainloop()

'''
def pause():
    try:
        # Usar raw string para evitar problemas com caracteres de escape
        command = (f"pause")
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        # Imprimir a saída padrão e a saída de erro, se houver
        print("Saída do script:")
        print(result.stdout)
        
        if result.stderr:
            print("Erro:")
            print(result.stderr)
        
    except Exception as e:
        print(f"Ocorreu um erro ao executar o script: {e}")
'''

#avisa para não desligar o pc
def tela_de_aviso(script_path):
    try:
        # Usar raw string para evitar problemas com caracteres de escape
        command = (f"{script_path}")
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        # Imprimir a saída padrão e a saída de erro, se houver
        print("Saída do script:")
        print(result.stdout)
        
        if result.stderr:
            print("Erro:")
            print(result.stderr)
        
    except Exception as e:
        print(f"Ocorreu um erro ao executar o script: {e}")

# Função que verifica se o BitLocker está ativo no drive
def is_bitlocker_encrypted(drive_letter):
    # Verifica se o script está rodando com privilégios de administrador
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False

    if not is_admin:
        print("Este script precisa ser executado com privilégios de administrador.")
        return False
    
    # Executa o comando manage-bde para verificar o status de criptografia do drive
    command = f"manage-bde -status {drive_letter}"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    # Verifica se a saída do comando contém a palavra "Criptografado" ou "Encrypted"
    return "Criptografado" in result.stdout or "Encrypted" in result.stdout

#função para matar a tarefa de aviso
# NOTE: os defaults eram `process_name=process_name` / `process_path=process_path`,
# referenciando o proprio parametro num nome que nunca existiu no modulo - isso
# dava NameError no momento em que o `def` era executado (o script morria ao importar).
def kill_process_by_name_or_path(process_name=None, process_path=None):
    try:
        # Se o nome do processo for fornecido, tentar matar pelo nome
        if process_name:
            subprocess.run(["taskkill", "/IM", process_name, "/F"], check=True)
            print(f"Processo {process_name} finalizado com sucesso.")
        # Se o caminho do processo for fornecido, tentar matar pelo PID
        elif process_path:
            # Encontrar o PID associado ao caminho do processo
            tasklist_output = subprocess.check_output(["tasklist", "/V", "/FO", "CSV"], encoding="utf-8")
            lines = tasklist_output.splitlines()

            # Percorre as linhas para encontrar o processo com o caminho especificado
            for line in lines:
                if process_path in line:
                    process_info = line.split('","')
                    pid = process_info[1]
                    # Matar o processo usando o PID
                    subprocess.run(["taskkill", "/PID", pid, "/F"], check=True)
                    print(f"Processo com PID {pid} finalizado com sucesso.")
                    return

            print(f"Nenhum processo encontrado com o caminho: {process_path}")
        else:
            print("Você precisa fornecer um nome de processo ou um caminho para matar o processo.")
    except subprocess.CalledProcessError as e:
        print(f"Erro ao tentar finalizar o processo: {e}")

#verifca se o bitlock esta ativo
def execute_exe_if_encrypted():
    while True:
        check_bitlocker_status(drive_letter)
        
        if is_bitlocker_encrypted(drive_letter):
            print(f"Disco {drive_letter} criptografado.", flush=True)
            return 0  # Retorna 0 se o disco está criptografado
        else:
            print("Disco não criptografado. Verificando novamente em 1 minuto.", flush=True)
            
            # Aguarda 1 minuto antes de verificar novamente
            time.sleep(60)
            
            # Verifica se o disco foi criptografado após a espera
            if not is_bitlocker_encrypted(drive_letter):
                print("O disco não está criptografado.", flush=True)
                return 1  # Retorna 1 se o disco ainda não está criptografad
            
script_path = str(AGENT_DIR / "start_notice_screen.bat")
def run_tela_de_aviso(script_path):
    tela_de_aviso(script_path)

# Inicia a execução em uma thread separada
def start_execution_in_thread():
    thread = threading.Thread(target=execute_exe_if_encrypted, args=())
    thread.start()
    return thread

#envia o progresso do bitlock pro firebase
def enviar_progresso_bitlocker_firebase(drive_letter="C:"):
    try:
        comando = f"manage-bde -status {drive_letter}"
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)

        log_completo = resultado.stdout.strip()
        print(f"Log do BitLocker:\n{log_completo}")  # debug opcional
        dados_status = {
            "remote": remote_status or "não configurado",
            "usuario": user2,
            "status_completo": log_completo,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        firebase_url = os.environ["FIREBASE_DATABASE_URL"] + "/status_bitlocker.json"
        response = requests.post(firebase_url, json=dados_status)

        if response.status_code == 200:
            print("Log do BitLocker enviado com sucesso.")
        else:
            print(f"Erro ao enviar log do BitLocker: {response.status_code}")
    except Exception as e:
        print(f"Erro ao enviar status ao Firebase: {e}")

user2 = verificar_nomeatual2() 

print(verificar_nomeatual())
verificar_nomeatual()

if verificar_nomeatual():
    # Criando a thread para rodar o bloqueio do Gerenciador de Tarefas
    task_manager_thread = threading.Thread(target=block_task_manager)
    task_manager_thread.start()

    print("\nUsuario ainda com a conta padrao", flush=True)

    #chamo a tela para pedir o email
    thread_renomear = threading.Thread(target=renomear_usuario)
    thread_renomear.start()
    thread_renomear.join()  
    time.sleep(5)

else:
    print("\no nome do usuario ja foi personalizado", flush=True)
    
    
    start_internet_monitor_thread()

    #chegando se o tmb esta ativado
    checar_tpm_e_popup()
    
    print("renomeando o PC")
    renomear_system_product_name()
    
    #caminha da tela de bloqueio
    script_path = str(AGENT_DIR / "start_notice_screen.bat")

    print("chamando a tela de aviso", flush=True)
    tela_thread = threading.Thread(target=run_tela_de_aviso, args=(script_path,))
    tela_thread.start()
    

    print("configurando o remote", flush=True)
    remote_status = configurar_remote()

    print("Chamando o bitlock", flush=True)
    enable_bitlocker()

    print("chamando o execute_exe_if_encrypted", flush=True)
    print (execute_exe_if_encrypted())
    # Criando a thread para executar o gerenciamento de bitlock em paralelo
    execution_thread = start_execution_in_thread()

    while True:
        
        def progresso_loop():
            while True:
                enviar_progresso_bitlocker_firebase()
                time.sleep(240)

        # e iniciar assim:
        progresso_thread = threading.Thread(target=progresso_loop)
        progresso_thread.daemon = True
        progresso_thread.start()
        
        if execute_exe_if_encrypted() == 0:
            print("Processos concluídos.", flush=True)
            time.sleep(60)
            
            start_execution_in_thread()
            
            time.sleep(30)
            bloquear_bitlocker()
            
            if execute_exe_if_encrypted() == 1:
                print("bitlock esta desativado, ativando novamente", flush=True)
                enable_bitlocker()
                
                time.sleep(10)
                
                print("removendo o arquivo do iniciar", flush=True)
                file_path = str(AGENT_DIR / "bitlocker_startup.bat")
                delete_file(file_path)
                
                time.sleep(1)
                
                print("removendo arquivo letra", flush=True)
                file_path = str(AGENT_DIR / "drive_letter_startup.bat")
                try:
                    delete_file(file_path)
                except Exception as e:
                    print(f"Erro ao remover arquivo letra: {e}")
                                    
                process_path = str(AGENT_DIR / "alert_screen.exe")
                process_name = "alert_screen.exe"
                #fechando o aviso de bitlock
                kill_process_by_name_or_path(process_name=process_name, process_path=process_path)
                
                
                time.sleep(60)
                
                print("removendo adm", flush=True)
                remover_admin(user2)
                
                time.sleep(1)
                
                print("alterando notificação")
                alterarnotficacao()
                
                time.sleep(1)
                
                delete_drive_x()
                
                time.sleep(10)
                
                alerta()
                
            else:
                
                print("removendo arquivo", flush=True)
                file_path = str(AGENT_DIR / "bitlocker_startup.bat")
                delete_file(file_path)

                time.sleep(1)
                
                print("removendo arquivo letra", flush=True)
                file_path = str(AGENT_DIR / "drive_letter_startup.bat")
                delete_file(file_path)                
                
                time.sleep(1)
                
                print("Foi verificado novmanete e está com bitlock", flush=True)
                process_path = str(AGENT_DIR / "alert_screen.exe")
                process_name = "alert_screen.exe"
                kill_process_by_name_or_path(process_name, process_path)
            
                time.sleep(1)
                
                print("deletando a partição x")
                delete_drive_x()
                
                time.sleep(1)
                
                print("removendo adm", flush=True)
                remover_admin(user2)
                
                print("alterando notificação")
                alterarnotficacao()
                
                time.sleep(10)
                
                alerta()

        else:
            print("continua", flush=True)
            pass
            


        
        
        


    
    
    