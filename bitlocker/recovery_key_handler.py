#5. alterar o nome do arquivo de recuperacao do bitlocker para o nome do computador
#6. copiar o arquivo de recuperacao do bitlocker e enviar via rede para um lugar (a ser determinado)
import getpass
import os
import shutil
import socket
from pathlib import Path


def renomear_e_mover_arquivo(caminho_arquivo, caminho_rede):
    """
    Renomeia um arquivo local com base no nome do computador e do usuário e move o arquivo para um diretório de rede.

    Parâmetros:
        caminho_arquivo (str): O caminho completo do arquivo a ser renomeado.
        caminho_rede (str): O caminho de destino na rede onde o arquivo será movido.
    """
    try:
        nome_computador = socket.gethostname()
        nome_usuario = getpass.getuser()
        
        diretorio, nome_arquivo_antigo = os.path.split(caminho_arquivo)
        extensao = os.path.splitext(nome_arquivo_antigo)[1]
        
        novo_nome_arquivo = f"{nome_computador} - {nome_usuario}{extensao}"
        novo_caminho_arquivo = os.path.join(diretorio, novo_nome_arquivo)
        
        os.rename(caminho_arquivo, novo_caminho_arquivo)
        print(f"Arquivo renomeado com sucesso para: {novo_caminho_arquivo}")
        
        destino_rede = os.path.join(caminho_rede, novo_nome_arquivo)
        shutil.move(novo_caminho_arquivo, destino_rede)
        print(f"Arquivo movido com sucesso para: {destino_rede}")
    
    except FileNotFoundError:
        print("O arquivo especificado não foi encontrado.")
    except Exception as e:
        print(f"Ocorreu um erro: {e}")

def processo():
    """
    Função principal que define o caminho do arquivo e da rede e chama a função de renomear e mover o arquivo.
    """
    caminho_arquivo = Path.home() / "Documents/a.txt"
    caminho_rede = os.environ.get("RECOVERY_SHARE_PATH", r"\\fileserver\recovery-share")
    renomear_e_mover_arquivo(caminho_arquivo, caminho_rede)

processo()