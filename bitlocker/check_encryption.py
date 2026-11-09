import ctypes
import subprocess
import time
from pathlib import Path


def is_bitlocker_encrypted(drive_letter="C:"):
    # Verifica se o script está rodando com privilégios de administrador
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False

    if not is_admin:
        print("Este script precisa ser executado com privilégios de administrador.")
        return False
    
    # Executa o comando manage-bde para verificar o status de criptografia do drive C:
    command = f"manage-bde -status {drive_letter}"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    # Verifica se a saída do comando contém a palavra "Criptografado"
    return "Criptografado" in result.stdout or "Encrypted" in result.stdout

def execute_exe_if_encrypted(executable_path):
    while True:
        if is_bitlocker_encrypted("C:"):
            print("Disco C: criptografado. Executando alert_screen.exe...")
            subprocess.run([executable_path])
            break  # Para o loop após rodar o executável
        else:
            print("Disco C: não criptografado. Verificando novamente em 1 minuto.")
        time.sleep(60)

if __name__ == "__main__":
    execute_exe_if_encrypted(Path(__file__).parent / "alert_screen.exe")
