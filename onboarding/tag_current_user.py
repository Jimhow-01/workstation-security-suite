import getpass
import os
from pathlib import Path


def obter_nome_usuario():
    # Obtém o nome do usuário logado
    return getpass.getuser().lower()

def UserWindows():
    try:
        UserWindows = obter_nome_usuario()
        
        # Define o caminho do arquivo onde o nome será salvo
        caminho_arquivo = os.path.join(str(Path.home() / 'shared-state'), "UserWindows.txt")
        
        with open(caminho_arquivo, "w") as arquivo:
            arquivo.write(f"{UserWindows}")
        
        print(f"O usuário do Windows '{UserWindows}' foi salvo em {caminho_arquivo}.")
    
    except Exception as e:
        print(f"Erro ao obter ou salvar o usuário do Windows: {e}")

UserWindows()
