import os
import tkinter as tk


def show_encryption_progress_screen():
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

show_encryption_progress_screen()
