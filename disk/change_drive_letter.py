import subprocess

import psutil


def get_drive_size(drive_letter):
    """Retorna o espaço total de uma unidade em MB."""
    try:
        usage = psutil.disk_usage(f"{drive_letter}:\\")
        return usage.total / (1024 * 1024)  # Retorna em MB
    except Exception as e:
        print(f"Erro ao verificar a unidade {drive_letter}: {e}")
        return None

def change_drive_letter(old_letter, new_letter):
    """Altera a letra da unidade usando diskpart."""
    try:
        # Cria o script para o diskpart
        script = f"""
        select volume {old_letter}
        assign letter={new_letter}
        """
        # Salva o script temporariamente
        with open("change_letter_script.txt", "w") as f:
            f.write(script)

        # Executa o diskpart com o script
        subprocess.run(["diskpart", "/s", "change_letter_script.txt"], check=True)
        print(f"Letra da unidade alterada de {old_letter} para {new_letter}")
    except Exception as e:
        print(f"Erro ao alterar a letra da unidade: {e}")

def find_and_set_x_drive():
    """Verifica partições menores que 20MB e altera a letra para 'X'."""
    found_small_drive = False

    # Itera por todas as partições no sistema
    for partition in psutil.disk_partitions(all=False):
        letter = partition.device.split(':')[0]  # Obtém a letra da unidade
        
        # Verifica o tamanho da partição
        size_in_mb = get_drive_size(letter)
        if size_in_mb and size_in_mb < 20:
            found_small_drive = True
            print(f"Unidade {letter}: tem {size_in_mb:.2f} MB")
            
            # Verifica se a letra da unidade já é 'X'
            if letter != 'X':
                print(f"A letra da unidade {letter} será alterada para 'X'.")
                change_drive_letter(letter, 'X')
            else:
                print("A unidade já tem a letra 'X'.")

    if not found_small_drive:
        print("Nenhuma partição com menos de 20MB foi encontrada.")

if __name__ == "__main__":
    find_and_set_x_drive()
