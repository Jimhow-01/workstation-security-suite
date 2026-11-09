import socket
from pathlib import Path


def nomedopc():
    # Obtém o nome do computador
    computer_name = socket.gethostname()
    return computer_name

def salvar_nome_pc_arquivo():
    # Obtém o nome do PC
    nome_pc = nomedopc()
    
    # Define o caminho do arquivo onde o nome será salvo
    caminho_arquivo = str(Path.home() / 'shared-state' / 'machine_tag.txt')
    
    try:
        # Abre o arquivo em modo de escrita e grava o nome do PC
        with open(caminho_arquivo, "w") as arquivo:
            arquivo.write(f"{nome_pc}")
        
        print(f"O nome do PC '{nome_pc}' foi salvo em {caminho_arquivo}.")
    
    except Exception as e:
        print(f"Erro ao salvar o nome do PC: {e}")

# Chama a função para salvar o nome do PC em um arquivo
salvar_nome_pc_arquivo()
