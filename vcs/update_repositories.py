import json
import os
import subprocess
import threading
import time

# Função que encontra repositórios SVN no diretório especificado
from pathlib import Path


def find_svn_repos(start_dir='C:/'):
    """
    Varre o sistema de arquivos a partir de um diretório inicial para encontrar repositórios SVN.
    Parâmetros:
        start_dir (str): O diretório inicial onde a busca por repositórios SVN começará (padrão 'C:/').
    Retorna:
        dict: Um dicionário contendo os caminhos dos repositórios SVN encontrados.
    """

    svn_repos = {}
    lock = threading.Lock()

    def scan_directory(root):
        """
        Varre um diretório específico à procura de repositórios SVN e suas subpastas.
        Parâmetros:
            root (str): O caminho do diretório raiz a ser escaneado.
        """
        try:
            for entry in os.scandir(root):
                # Verificar se o caminho contém $Recycle.Bin e ignorar
                if '$Recycle.Bin' not in entry.path:
                    if entry.is_dir(follow_symlinks=False):
                        svn_path = os.path.join(entry.path, '.svn')
                        if os.path.isdir(svn_path):
                            with lock:
                                svn_repos[entry.path] = {}
                        else:
                            scan_directory(entry.path)  # Recursivamente varre as subpastas
        except PermissionError:
            pass

    scan_thread = threading.Thread(target=scan_directory, args=(start_dir,))
    scan_thread.start()
    scan_thread.join()

    return svn_repos

# Função que salva os repositórios em um arquivo JSON
def save_repos_to_json(repos, filename='svn_repos.json'):
    public_documents_dir = os.path.join(os.environ['PUBLIC'], 'Documents')  
    json_file_path = os.path.join(public_documents_dir, filename)

    with open(json_file_path, 'w') as json_file:
        json.dump(repos, json_file, indent=4)

# Função que carrega os repositórios de um arquivo JSON, se existir
def load_repos_from_json(filename='svn_repos.json'):
    if os.path.exists(filename):
        with open(filename) as json_file:
            return json.load(json_file)
    return {}

# Função para executar comandos no terminal (usado para rodar comandos SVN)
def run_command(command, cwd):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return process

# Função que atualiza um repositório SVN
def update_svn_repo(repo_path):
    try:
        print(f"Updating repository at {repo_path}...")
        process = run_command(['svn', 'update'], repo_path)

        for line in process.stdout:
            print(line, end='')

        process.stdout.close()
        process.wait()

        if process.returncode != 0:
            process.stderr.seek(0)
            stderr_output = process.stderr.read()
            
            if 'svn cleanup' in stderr_output:
                print(f"\nError updating repository at {repo_path}: {stderr_output.strip()}")
                print("Attempting to clean up...")

                cleanup_process = run_command(['svn', 'cleanup'], repo_path)
                for line in cleanup_process.stdout:
                    print(line, end='')

                cleanup_process.stdout.close()
                cleanup_process.wait()

                if cleanup_process.returncode == 0:
                    print("Cleanup successful. Retrying update...")
                    retry_process = run_command(['svn', 'update'], repo_path)
                    for line in retry_process.stdout:
                        print(line, end='')

                    retry_process.stdout.close()
                    retry_process.wait()

                    if retry_process.returncode != 0:
                        retry_process.stderr.seek(0)
                        retry_stderr_output = retry_process.stderr.read()
                        print(f"Error during retry update: {retry_stderr_output.strip()}")
                else:
                    cleanup_process.stderr.seek(0)
                    cleanup_stderr_output = cleanup_process.stderr.read()
                    print(f"Error during cleanup: {cleanup_stderr_output.strip()}")
            else:
                print(f"Error updating repository at {repo_path}: {stderr_output.strip()}")
    except Exception as e:
        print(f"Exception while updating repository at {repo_path}: {e}")

# Função que atualiza todos os repositórios encontrados
def update_all_repos(repos):
    threads = []
    
    for repo_path in repos.keys():
        t = threading.Thread(target=update_svn_repo, args=(repo_path,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

# Função principal que executa o processo completo
def realizar():
    json_filename = 'svn_repos.json'
    existing_repos = load_repos_from_json(json_filename)
    print("Loaded existing repositories from JSON...")

    repos = find_svn_repos(os.environ.get('SCAN_ROOT', str(Path.home())))
    save_repos_to_json(repos, json_filename)
    print("Scan completed and JSON file updated.")

    update_all_repos(repos)
    print("All repositories have been updated.")
    time.sleep(3)

realizar()