# uac_watcher_simple.py
# Dependências: pip install pywin32
# Execute como Administrador (ou instale como serviço / task)
import json
import os
import threading
import time
import winreg
from datetime import datetime
from pathlib import Path

import win32con
import win32file

WATCH_DIR = os.environ.get('WATCH_DIR', str(Path.home() / 'security-requests'))
LOG_PATH = str(Path.cwd() / 'uac_watcher.log')

def log(msg):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} - {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def read_uac_values():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                             0, winreg.KEY_READ)
        val1, _ = winreg.QueryValueEx(key, "ConsentPromptBehaviorAdmin")
        val2, _ = winreg.QueryValueEx(key, "PromptOnSecureDesktop")
        winreg.CloseKey(key)
        return int(val1), int(val2)
    except Exception as e:
        log(f"Erro lendo UAC: {e}")
        return None, None

def set_uac_values(consent_behavior:int, prompt_secure_desktop:int):
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "ConsentPromptBehaviorAdmin", 0, winreg.REG_DWORD, int(consent_behavior))
        winreg.SetValueEx(key, "PromptOnSecureDesktop", 0, winreg.REG_DWORD, int(prompt_secure_desktop))
        winreg.CloseKey(key)
        log(f"UAC set: ConsentPromptBehaviorAdmin={consent_behavior}, PromptOnSecureDesktop={prompt_secure_desktop}")
        return True
    except PermissionError:
        log("Permissão negada ao tentar escrever registro. Rode como Administrador.")
        return False
    except Exception as e:
        log(f"Erro ao setar UAC: {e}")
        return False

def revert_after(original_cb, original_psd, delay_seconds=60):
    def _revert():
        log(f"Esperando {delay_seconds}s para reverter UAC...")
        time.sleep(delay_seconds)
        set_uac_values(original_cb, original_psd)
        log("UAC revertido.")
    threading.Thread(target=_revert, daemon=True).start()

def process_trigger(fullpath):
    log(f"Processando trigger: {fullpath}")
    try:
        with open(fullpath, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        log(f"Falha ao ler JSON do gatilho: {e}")
        try: os.remove(fullpath)
        except: pass
        return

    user = doc.get("user", "unknown")
    reason = doc.get("reason", "")
    duration = int(doc.get("duration", 60))
    # Esses valores serão aplicados temporariamente:
    # aqui definimos consent_behavior=0 (menor prompt) e prompt_secure_desktop=0
    # Você pode ajustar new_cb/new_psd se quiser outro comportamento.
    log(f"Trigger from: {user} reason: {reason} duration: {duration}s")

    orig_cb, orig_psd = read_uac_values()
    if orig_cb is None:
        log("Não foi possível ler UAC original. Abortando trigger.")
        try: os.remove(fullpath)
        except: pass
        return

    new_cb = 0   # EXEMPLO: 0 = reduzir prompts (ajuste conforme necessário)
    new_psd = 0

    if set_uac_values(new_cb, new_psd):
        revert_after(orig_cb, orig_psd, delay_seconds=duration)
    else:
        log("Falha ao aplicar novos valores UAC.")

    # apagar gatilho
    try:
        os.remove(fullpath)
        log(f"Gatilho apagado: {fullpath}")
    except Exception as e:
        log(f"Erro apagando gatilho: {e}")

def ensure_watch_dir():
    os.makedirs(WATCH_DIR, exist_ok=True)
    # garante arquivo de log criado
    try:
        open(LOG_PATH, "a").close()
    except Exception:
        pass

def watch_loop():
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

if __name__ == "__main__":
    log("uac_watcher_simple iniciado")
    watch_loop()
