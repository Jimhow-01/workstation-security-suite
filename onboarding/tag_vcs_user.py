import os
from pathlib import Path


def get_svn_user():
    auth_dir = os.path.join(os.getenv('APPDATA'), 'Subversion', 'auth', 'svn.simple')
    
    if not os.path.exists(auth_dir):
        print("Pasta de configuração não encontrada.")
        return None
    
    for root, dirs, files in os.walk(auth_dir):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path) as f:
                lines = f.readlines()
                for i in range(len(lines)):
                    if lines[i].strip() == 'username':
                        if i + 2 < len(lines):
                            username = lines[i + 2].strip()
                            return username

def SvnUser():
    # Obtém o nome do PC
    userSVN = get_svn_user()
    
    # Define o caminho do arquivo onde o nome será salvo
    caminho_arquivo = str(Path.home() / 'shared-state' / 'vcs_user.txt')
    
    try:
        # Abre o arquivo em modo de escrita e grava o nome do PC
        with open(caminho_arquivo, "w") as arquivo:
            arquivo.write(f"{userSVN}")
        
        print(f"O User do svn '{userSVN}' foi salva em {caminho_arquivo}.")
    
    except Exception as e:
        print(f"Erro ao salvar a usuario do svn: {e}")
    
SvnUser()