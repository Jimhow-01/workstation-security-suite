# gera um nome para o computador seguindo o padrao WS-xxxxx
import ctypes
import os
import random
import string
import sys
import time


def gerar_novo_nome(prefixo="WS-", tamanho=4):
    """
    Gera um novo nome para o computador, combinando um prefixo com um sufixo numérico aleatório.

    Parâmetros:
        prefixo (str): O prefixo a ser usado no novo nome (default: "WS-").
        tamanho (int): O número de dígitos a ser gerado para o sufixo (default: 4).

    Retorna:
        str: O novo nome gerado.
    """
    sufixo = ''.join(random.choices(string.digits, k=tamanho))
    return f"{prefixo}{sufixo}"

def renomear_computador(novo_nome):
    """
    Renomeia o computador usando o comando `wmic` e solicita a reinicialização do sistema.

    Parâmetros:
        novo_nome (str): O novo nome para o computador.
    """
    comando = f"wmic computersystem where name=\"%computername%\" call rename name=\"{novo_nome}\""
    resultado = os.system(comando)

    if resultado == 0:
        print(f"O nome do computador foi alterado para {novo_nome}. Será necessário reiniciar o sistema para aplicar a alteração.")
    else:
        print(f"Falha ao renomear o computador. Código de retorno: {resultado}. Certifique-se de que o script está sendo executado como administrador.")
    
    time.sleep(5)

def solicitar_permissoes_admin():
    """
    Solicita permissões de administrador para a execução do script, se necessário.
    Se não for executado como administrador, o script reiniciará com as permissões elevadas.
    """
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("Reiniciando o script com permissões de administrador...")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, ' '.join(sys.argv), None, 1)
        sys.exit()

def renomeia():
    """
    Função principal que solicita permissões de administrador, gera um novo nome para o computador
    e renomeia o computador.
    """
    solicitar_permissoes_admin()
    novo_nome = gerar_novo_nome()
    renomear_computador(novo_nome)


if __name__ == "__main__":
    # NOTE: `renomeia()` rodava em nivel de modulo - importar este arquivo ja
    # pedia elevacao de privilegio e renomeava a maquina (e chamava sys.exit()
    # se o processo nao fosse admin). Agora so roda na execucao direta.
    renomeia()