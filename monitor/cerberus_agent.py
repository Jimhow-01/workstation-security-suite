import getpass

# NOTE: cert_reqs=CERT_NONE / check_hostname=False desabilitam a validacao do
# certificado do no de monitoramento (que usava certificado autoassinado em rede
# fechada). Aceita qualquer certificado apresentado por qualquer host na rede.
# Correto: distribuir a CA interna e validar a cadeia, ou pinar o certificado.
import hashlib
import json
import logging
import os
import platform
import socket
import ssl
import subprocess
import threading
import time
import winreg

import requests
import websocket
from cryptography.fernet import Fernet

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nos de monitoramento (defina MONITOR_NODES="node1,node2,...")
MONITOR_NODES: list[str] = [n.strip() for n in os.environ.get("MONITOR_NODES", "").split(",") if n.strip()]

# Chave de criptografia (obtida do ambiente; gere com Fernet.generate_key())
ENCRYPTION_KEY: bytes = os.environ["AGENT_ENCRYPTION_KEY"].encode()
cipher: Fernet = Fernet(ENCRYPTION_KEY)

# Caminhos para arquivos locais criptografados
LOCAL_DATA_FILE: str = "cerberus_data.enc"
INTERNET_LOSS_FILE: str = "internet_loss.enc"
STATE_CHANGE_LOG_FILE: str = "state_changes.enc"

def get_computer_info() -> tuple:
    """
    Obtém o nome do computador e o nome do usuário do sistema atual.
    """
    computer_name: str = platform.node()
    user_name: str = getpass.getuser()
    return computer_name, user_name

def get_firewall_rules() -> list[dict[str, any]] | None:
    """
    Obtém as regras de firewall ativas usando PowerShell e retorna como uma lista de dicionários.
    """
    try:
        # Comando PowerShell para obter regras de firewall ativas com mais detalhes
        command = [
            "powershell.exe", 
            "-Command", 
            "Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' } | Select-Object DisplayName, Direction, Action, Profile, Enabled | ConvertTo-Json"
        ]
        
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            raise Exception(result.stderr)
        
        firewall_rules = json.loads(result.stdout)
        return firewall_rules if isinstance(firewall_rules, list) else [firewall_rules]
        
    except subprocess.TimeoutExpired:
        logging.error("Tempo esgotado ao verificar as regras de firewall.")
        return None
    except Exception as e:
        logging.error(f"Erro ao obter as regras de firewall: {e}")
        return None

def get_installed_programs() -> list[str]:
    """
    Busca a lista de programas instalados no Registro do Windows.
    """
    # Caminhos do registro para programas instalados
    registry_paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    ]
    
    installed_programs = []

    for reg_path in registry_paths:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
            for i in range(0, winreg.QueryInfoKey(key)[0]):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    program_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                    installed_programs.append(program_name)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Erro ao ler o caminho do registro {reg_path}: {e}")
    
    return installed_programs

def save_encrypted_data(data: dict[str, any], path: str) -> None:
    """
    Salva os dados em um arquivo de forma criptografada.
    """
    encrypted_data: bytes = cipher.encrypt(json.dumps(data).encode())
    with open(path, "wb") as f:
        f.write(encrypted_data)

def load_encrypted_data(path: str) -> dict[str, any] | None:
    """
    Carrega dados de um arquivo criptografado e os decifra.
    """
    if os.path.exists(path):
        with open(path, "rb") as f:
            encrypted_data: bytes = f.read()
        data = json.loads(cipher.decrypt(encrypted_data).decode())
        return data
    return None

def test_node_speed(ip: str) -> float:
    """
    Testa a velocidade de resposta para um monitor node enviando uma mensagem ping via WebSocket.
    """
    try:
        start_time = time.time()
        ws = websocket.create_connection(
            f"wss://{ip}:8433",
            sslopt={  # NOTE: validacao de certificado desabilitada - ver comentario no topo do modulo
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False
            },
            timeout=10
        )
        ping_message = json.dumps({"type": "ping"})
        ws.send(ping_message)
        response = ws.recv()
        if response:
            data = json.loads(response)
            if data.get('type') == 'pong':
                end_time = time.time()
                ws.close()
                response_time = (end_time - start_time) * 1000  # em milissegundos
                logging.info(f"Tempo de resposta para monitor node {ip}: {response_time} ms")
                return response_time
        ws.close()
        logging.error(f"monitor node {ip} não respondeu corretamente ao ping.")
        return float('inf')
    except Exception as e:
        logging.error(f"Erro ao conectar ao monitor node {ip}: {e}")
        return float('inf')

def connect_and_register(node_ip: str, computer_name: str, user_name: str, firewall_rules: list[dict[str, any]]) -> None:
    """
    Conecta ao node de monitoramento mais rapido e registra o Cerberus com seus detalhes.
    """
    try:
        ws = websocket.create_connection(
            f"wss://{node_ip}:8433",
            sslopt={
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False
            }
        )
        registration_data = {
            "computer_name": computer_name,
            "user_name": user_name,
            "firewall_rules": firewall_rules
        }
        ws.send(json.dumps(registration_data))
        response = ws.recv()
        if response:
            data = json.loads(response)
            if data.get('status') == 'registered':
                logging.info(f"Registrado com monitor node {node_ip}")
            else:
                logging.error(f"Falha ao registrar com monitor node {node_ip}")
        ws.close()
    except Exception as e:
        logging.error(f"Falha ao conectar ao monitor node {node_ip}: {e}")

def ping_test(address: str) -> bool:
    """
    Testa a conectividade de rede pingando um endereço IP externo.
    """
    try:
        socket.create_connection((address, 80), timeout=5)
        return True
    except Exception:
        return False

def calculate_file_hash(file_path: str) -> str:
    """
    Calcula o hash SHA-256 do arquivo especificado.
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        logging.error(f"Erro ao calcular o hash para {file_path}: {e}")
        return ""

def download_file_with_integrity(url: str, checksum: str, destination_path: str) -> bool:
    """
    Faz o download de um arquivo e confirma sua integridade comparando seu checksum.
    Tenta até 5 vezes se ocorrer algum problema.
    """
    attempts = 0
    while attempts < 5:
        attempts += 1
        try:
            logging.info(f"Tentando fazer o download do arquivo (Tentativa {attempts}): {url}")
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            with open(destination_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            # Verificar a integridade do arquivo
            file_hash = calculate_file_hash(destination_path)
            if file_hash.lower() == checksum.lower():
                logging.info(f"Arquivo baixado e verificado com sucesso: {destination_path}")
                return True
            else:
                logging.error("Falha na verificação de integridade do arquivo.")
                os.remove(destination_path)
        except Exception as e:
            logging.error(f"Erro ao baixar o arquivo: {e}")
    logging.error("Falha ao baixar e verificar o arquivo após 5 tentativas.")
    return False

def keep_alive(node_ip: str, computer_name: str) -> None:
    """
    Envia mensagens de keep-alive periódicas para o monitor node.
    """
    failed_attempts = 0
    while True:
        try:
            ws = websocket.create_connection(
                f"wss://{node_ip}:8433",
                sslopt={  # NOTE: validacao de certificado desabilitada - ver comentario no topo
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False
                },
                timeout=10
            )
            keep_alive_message = json.dumps({"type": "keep_alive", "computer_name": computer_name})
            ws.send(keep_alive_message)
            response = ws.recv()
            if response:
                data = json.loads(response)
                if data.get('status') == 'keep_alive_ack':
                    logging.info(f"Keep-alive reconhecido pelo monitor node {node_ip}")
            ws.close()
            failed_attempts = 0
        except Exception as e:
            logging.error(f"Falha no keep-alive para monitor node {node_ip}: {e}")
            failed_attempts += 1
            if failed_attempts >= 3:
                handle_disconnect(node_ip, computer_name)
                break
        time.sleep(10)

def handle_disconnect(node_ip: str, computer_name: str) -> None:
    """
    Lida com a desconexão de rede tentando reconectar e gerenciar a perda de internet.
    """
    logging.warning("Nenhum monitor node respondeu. Verificando conexão com a internet...")
    attempts = 0
    while True:
        if ping_test('8.8.8.8') or ping_test('1.1.1.1'):
            # Internet está disponível, tentar outros nodes de monitoramento
            for ip in MONITOR_NODES:
                if ip != node_ip:
                    logging.info(f"Tentando conectar ao monitor node {ip}")
                    new_response_time = test_node_speed(ip)
                    if new_response_time != float('inf'):
                        # Encontrou um monitor node acessível
                        threading.Thread(target=keep_alive, args=(ip, computer_name), daemon=True).start()
                        threading.Thread(target=listen_for_messages, args=(ip, computer_name), daemon=True).start()
                        return
            # Após 4 tentativas com internet mas sem monitor node, iniciar executável
            attempts += 1
            if attempts >= 4:
                logging.info("Internet está disponível, mas nenhum monitor node respondeu. Iniciando executável.")
                # Placeholder: Iniciar executável com caminho hardcoded
                # subprocess.Popen(['path_to_executable'])
                return
            time.sleep(10)
        else:
            # Internet não está disponível
            logging.warning("Conexão com a internet perdida.")
            # Salvar em um novo arquivo criptografado local
            data = {
                "timestamp": time.time(),
                "reason": "Internet lost"
            }
            save_encrypted_data(data, INTERNET_LOSS_FILE)
            # Impedir que o usuário copie arquivos (Placeholder)
            # Implementar prevenção de cópia de arquivos aqui
            while not (ping_test('8.8.8.8') or ping_test('1.1.1.1')):
                logging.info("Aguardando restauração da conexão com a internet...")
                time.sleep(10)
            logging.info("Conexão com a internet restaurada.")
            # Reexecutar os passos 1, 2 e 3
            return  # Retornar para permitir que o loop principal reinicialize

def listen_for_messages(node_ip: str, computer_name: str) -> None:
    """
    Escuta por mensagens do monitor node e lida com comandos e downloads de arquivos.
    """
    while True:
        try:
            ws = websocket.create_connection(
                f"wss://{node_ip}:8433",
                sslopt={  # NOTE: validacao de certificado desabilitada - ver comentario no topo
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False
                },
                timeout=10
            )
            listen_message = json.dumps({"type": "listen", "computer_name": computer_name})
            ws.send(listen_message)
            response = ws.recv()
            if response:
                message = json.loads(response)
                if 'command' in message:
                    command = message['command']
                    # Executar o comando (script Python)
                    try:
                        exec(command)
                    except Exception as e:
                        logging.error(f"Erro ao executar o comando: {e}")
                if 'file' in message:
                    # Implementar download de arquivo e verificação de integridade
                    file_info = message['file']
                    url = file_info.get('url')
                    checksum = file_info.get('checksum')
                    destination_path = file_info.get('destination_path', 'downloaded_file')
                    if url and checksum:
                        success = download_file_with_integrity(url, checksum, destination_path)
                        if success:
                            logging.info(f"Arquivo '{destination_path}' baixado e verificado com sucesso.")
                        else:
                            logging.error(f"Falha ao baixar ou verificar o arquivo '{destination_path}'.")
                    else:
                        logging.error("Informações de arquivo inválidas recebidas.")
            ws.close()
            time.sleep(5)
        except Exception as e:
            logging.error(f"Erro ao escutar por mensagens: {e}")
            time.sleep(10)

def monitor_changes(computer_name: str) -> None:
    """
    Monitora mudanças em programas instalados e regras de firewall a cada 60 segundos.
    Registra localmente as alterações de forma criptografada e as envia ao monitor node.
    """
    last_programs = get_installed_programs()
    last_firewall_rules = get_firewall_rules()
    while True:
        time.sleep(60)
        # Monitorar programas instalados
        current_programs = get_installed_programs()
        if current_programs != last_programs:
            added_programs = set(current_programs) - set(last_programs)
            removed_programs = set(last_programs) - set(current_programs)
            changes = {}
            if added_programs:
                changes['programs_added'] = list(added_programs)
                logging.info(f"Programas adicionados: {added_programs}")
            if removed_programs:
                changes['programs_removed'] = list(removed_programs)
                logging.info(f"Programas removidos: {removed_programs}")
            if changes:
                # Registrar localmente de forma criptografada
                changes['timestamp'] = time.time()
                save_encrypted_data(changes, STATE_CHANGE_LOG_FILE)
                # Enviar as alterações para o monitor node
                send_state_changes(changes, computer_name)
            last_programs = current_programs
        # Monitorar regras de firewall
        current_firewall_rules = get_firewall_rules()
        if current_firewall_rules != last_firewall_rules:
            added_rules = [rule for rule in current_firewall_rules if rule not in last_firewall_rules]
            removed_rules = [rule for rule in last_firewall_rules if rule not in current_firewall_rules]
            changes = {}
            if added_rules:
                changes['firewall_rules_added'] = added_rules
                logging.info(f"Regras de firewall adicionadas: {added_rules}")
            if removed_rules:
                changes['firewall_rules_removed'] = removed_rules
                logging.info(f"Regras de firewall removidas: {removed_rules}")
            if changes:
                # Registrar localmente de forma criptografada
                changes['timestamp'] = time.time()
                save_encrypted_data(changes, STATE_CHANGE_LOG_FILE)
                # Enviar as alterações para o monitor node
                send_state_changes(changes, computer_name)
            last_firewall_rules = current_firewall_rules

def send_state_changes(changes: dict[str, any], computer_name: str) -> None:
    """
    Envia as alterações de estado para o monitor node.
    """
    try:
        # Selecionar o node de monitoramento mais rapido
        response_times = {ip: test_node_speed(ip) for ip in MONITOR_NODES}
        fastest_node = min(response_times, key=response_times.get)
        ws = websocket.create_connection(
            f"wss://{fastest_node}:8433",
            sslopt={
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False
            }
        )
        message = {
            "type": "state_change",
            "computer_name": computer_name,
            "changes": changes
        }
        ws.send(json.dumps(message))
        response = ws.recv()
        if response:
            data = json.loads(response)
            if data.get('status') == 'state_change_ack':
                logging.info("Alterações de estado enviadas e reconhecidas pelo monitor node.")
                if os.path.exists(STATE_CHANGE_LOG_FILE):
                    os.remove(STATE_CHANGE_LOG_FILE)
            else:
                logging.error("Falha ao enviar alterações de estado para o monitor node.")
        ws.close()
    except Exception as e:
        logging.error(f"Erro ao enviar alterações de estado para o monitor node: {e}")

def main():
    """
    Função principal para inicializar o Cerberus, coletar informações do sistema, selecionar o node de monitoramento mais rapido e manter a conexão.
    """
    while True:
        try:
            # Passos 1 e 2
            response_times = {ip: test_node_speed(ip) for ip in MONITOR_NODES}
            fastest_node = min(response_times, key=response_times.get)
            logging.info(f"node de monitoramento mais rapido: {fastest_node}")
            # Passos 3 e 4
            computer_name, user_name = get_computer_info()
            firewall_rules = get_firewall_rules()
            installed_programs = get_installed_programs()
            data = {
                "monitor_nodes": MONITOR_NODES,
                "computer_name": computer_name,
                "user_name": user_name,
                "firewall_rules": firewall_rules,
                "installed_programs": installed_programs
            }
            if os.path.exists(LOCAL_DATA_FILE):
                existing_data = load_encrypted_data(LOCAL_DATA_FILE)
                existing_data['node_ips'] = MONITOR_NODES
                save_encrypted_data(existing_data, LOCAL_DATA_FILE)
            else:
                save_encrypted_data(data, LOCAL_DATA_FILE)
            
            connect_and_register(fastest_node, computer_name, user_name, firewall_rules)
        
            threading.Thread(target=keep_alive, args=(fastest_node, computer_name), daemon=True).start()
            threading.Thread(target=listen_for_messages, args=(fastest_node, computer_name), daemon=True).start()
            threading.Thread(target=monitor_changes, args=(computer_name,), daemon=True).start()
            
            while True:
                time.sleep(1)
        except Exception as e:
            logging.error(f"Ocorreu um erro no loop principal: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
