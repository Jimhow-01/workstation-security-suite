import os
import subprocess


def delete_drive_x():
    """Exclui completamente o disco com a letra X usando o diskpart."""
    script_content = """
    select volume X
    delete volume
    """
    
    script_path = "delete_drive_script.txt"
    
    try:
        # Salva o script temporariamente
        with open(script_path, "w") as f:
            f.write(script_content)

        # Verifica se o arquivo de script foi criado corretamente
        if not os.path.exists(script_path):
            raise FileNotFoundError("O script para excluir o volume não foi criado corretamente.")

        # Executa o diskpart com o script
        result = subprocess.run(["diskpart", "/s", script_path], check=True, capture_output=True, text=True)

        print("Disco X excluído com sucesso.")
        print(result.stdout)

    except FileNotFoundError as fnf_error:
        print(f"Erro: {fnf_error}")
        
    except subprocess.CalledProcessError as e:
        print(f"Erro ao excluir o disco X (code: {e.returncode}):")
        print(f"Saída de erro (stderr): {e.stderr.strip()}")
        print(f"Saída padrão (stdout): {e.stdout.strip()}")
        
    except Exception as ex:
        print(f"Ocorreu um erro inesperado: {ex}")

    finally:
        # Remove o arquivo de script temporário após a execução
        if os.path.exists(script_path):
            os.remove(script_path)
