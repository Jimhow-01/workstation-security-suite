import subprocess
import tkinter as tk
from tkinter import messagebox

# Conta padrao criada no provisioning da estacao
DEFAULT_ACCOUNT = "workstation-default"

def renomear_usuario():
    def verificar_usuario_existe(usuario):
        try:
            comando_verificar = f'Get-LocalUser -Name "{usuario}"'
            resultado = subprocess.run(
                ["powershell", "-Command", comando_verificar],
                capture_output=True,
                text=True
            )

            if resultado.returncode != 0:
                print(f"Usuário '{usuario}' não encontrado.")
                return False
            return True
        except Exception as erro:
            print(f"Erro ao verificar usuário: {erro}")
            return False
   
    def listar_usuarios():
        try:
            comando_listar = 'Get-LocalUser | Select-Object -ExpandProperty Name'
            resultado = subprocess.run(
                ["powershell", "-Command", comando_listar],
                capture_output=True,
                text=True
            )

            if resultado.returncode == 0 and resultado.stdout.strip():
                usuarios = resultado.stdout.strip().splitlines()
                return usuarios
            else:
                print("Nenhum usuário encontrado.")
                return []
        except Exception as erro:
            print(f"Erro ao listar usuários: {erro}")
            return []
        
    listar_usuarios()
    
    def renomear_usuario_windows(usuario_atual, novo_nome):
        if not verificar_usuario_existe(usuario_atual):
            messagebox.showerror("Erro", f"Não foi possível renomear. O usuário '{usuario_atual}' não existe.")
            return

        try:
            comando = f'rename-localuser -name "{usuario_atual}" -newname "{novo_nome}"'
            resultado = subprocess.run(
                ["powershell", "-Command", comando],
                check=False,
                capture_output=True,
                text=True
            )

            if resultado.returncode == 0:
                messagebox.showinfo("Sucesso", f"Usuário renomeado de {usuario_atual} para {novo_nome} com sucesso.")
                root.quit()  # Encerra a janela Tkinter
            else:
                messagebox.showerror("Erro", f"Erro ao renomear o usuário. Código de erro: {resultado.returncode}\n{resultado.stderr}")

        except Exception as erro:
            messagebox.showerror("Erro", f"Ocorreu um erro inesperado: {erro}")

    def on_renomear_click():
        novo_nome = entry_novo_nome.get()
        if not novo_nome:
            messagebox.showwarning("Atenção", "Por favor, insira um novo nome de usuário.")
            return

        if usuarios:
            usuario_a_renomear = DEFAULT_ACCOUNT  # Seleciona o primeiro usuário da lista
            renomear_usuario_windows(usuario_a_renomear, novo_nome)

    root = tk.Tk()
    root.title("Renomear Usuário")

    usuarios = listar_usuarios()

    label_instrucoes = tk.Label(root, text="Insira o novo nome do usuário:")
    label_instrucoes.pack(pady=10)

    entry_novo_nome = tk.Entry(root)
    entry_novo_nome.pack(pady=10)

    button_renomear = tk.Button(root, text="Renomear Usuário", command=on_renomear_click)
    button_renomear.pack(pady=20)

    root.mainloop()

renomear_usuario()