import getpass
import json
import os
import socket
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import requests

# 🔧 Ajuste este caminho para o mesmo usado no watcher
WATCH_DIR = os.environ.get('WATCH_DIR', str(Path.home() / 'security-requests'))
FIREBASE_URL = os.environ["FIREBASE_DATABASE_URL"] + "/permissions.json"

def create_trigger(user, reason, program_path, duration=60):
    payload = {
        "user": user,
        "device": socket.gethostname(),
        "reason": reason,
        "program_path": program_path,
        "duration": duration,
        "timestamp": int(time.time())
    }

    # Garante que a pasta existe
    os.makedirs(WATCH_DIR, exist_ok=True)

    # Nome do arquivo com timestamp
    filename = os.path.join(WATCH_DIR, f"trigger_{int(time.time())}.json")

    # Grava JSON local
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    # Envia também para Firebase
    try:
        r = requests.post(FIREBASE_URL, json=payload, timeout=10)
        if r.status_code == 200:
            return True, filename
        else:
            return False, f"Firebase retornou {r.status_code}: {r.text}"
    except Exception as e:
        return False, f"Erro ao enviar para Firebase: {e}"

def escolher_programa():
    caminho = filedialog.askopenfilename(
        title="Selecione o programa para executar como administrador",
        filetypes=[("Executáveis", "*.exe"), ("Todos os arquivos", "*.*")]
    )
    if caminho:
        programa_var.set(caminho)
        programa_label.config(text=f"Programa selecionado:\n{caminho}")

def enviar():
    reason = motivo_entry.get().strip()
    program_path = programa_var.get().strip()

    if not reason:
        messagebox.showwarning("Atenção", "O motivo do acesso não pode ficar em branco!")
        return
    if not program_path:
        messagebox.showwarning("Atenção", "Você deve selecionar um programa para executar!")
        return

    user = getpass.getuser()
    ok, result = create_trigger(user=user, reason=reason, program_path=program_path, duration=60)

    if ok:
        messagebox.showinfo(
            "Solicitação enviada",
            "O time de TI foi contactado.\n\n"
            "O programa selecionado será executado como administrador, pode haver um certo delay."
        )
        root.destroy()
    else:
        messagebox.showerror("Erro", result)

# --- Interface ---
root = tk.Tk()
root.title("Solicitação de Permissão Temporária")

tk.Label(root, text="Motivo do acesso:", font=("Segoe UI", 11)).pack(padx=10, pady=5)

motivo_entry = tk.Entry(root, width=50, font=("Segoe UI", 10))
motivo_entry.pack(padx=10, pady=5)
motivo_entry.focus()

programa_var = tk.StringVar()

tk.Button(
    root, text="Selecionar Programa",
    command=escolher_programa,
    bg="#444", fg="white",
    font=("Segoe UI", 10, "bold")
).pack(pady=10)

programa_label = tk.Label(root, text="Nenhum programa selecionado", font=("Segoe UI", 9), fg="gray")
programa_label.pack(padx=10, pady=5)

enviar_btn = tk.Button(
    root, text="Enviar",
    command=enviar,
    bg="#0078D7", fg="white",
    font=("Segoe UI", 10, "bold")
)
enviar_btn.pack(pady=15)

root.mainloop()
