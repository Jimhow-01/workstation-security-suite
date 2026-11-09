import ctypes
import os
import subprocess
from pathlib import Path

import pygame


# Função para verificar se o disco C: está criptografado com BitLocker
def is_bitlocker_encrypted(drive_letter):
    # Verifica se o script está rodando com privilégios de administrador
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False

    if not is_admin:
        print("Este script precisa ser executado com privilégios de administrador.")
        return False
    
    # Executa o comando manage-bde para verificar o status de criptografia do drive
    command = f"manage-bde -status {drive_letter}"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    # Verifica se a saída do comando contém a palavra "Criptografado" ou "Encrypted"
    return "Criptografado" in result.stdout or "Encrypted" in result.stdout

# Função para excluir o arquivo especificado
def delete_file(file_path):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Arquivo excluído: {file_path}")
        else:
            print(f"Arquivo não encontrado: {file_path}")
    except Exception as e:
        print(f"Erro ao excluir o arquivo: {e}")

# Função para encerrar um processo pelo Task Manager
def kill_process(process_name):
    try:
        subprocess.run(f'taskkill /IM {process_name} /F', shell=True)
        print(f"Processo encerrado: {process_name}")
    except Exception as e:
        print(f"Erro ao encerrar o processo: {e}")

# Função para exibir a tela de alerta
def show_alert_screen():
    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption('Alerta de Criptografia: SUCESSO!')

    # Obtém as dimensões da tela
    screen_width, screen_height = screen.get_size()

    # Cores
    GRAY = (169, 169, 169)
    YELLOW = (255, 255, 0)
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    BUTTON_COLOR_DEFAULT = WHITE
    BUTTON_COLOR_HOVER = BLACK

    # Fonte e botão
    button_font = pygame.font.Font(None, 50)
    message_font = pygame.font.Font(None, 40)

    # Mensagem e botão "OK"
    message_text = message_font.render('BitLocker feito com sucesso, clique em "OK" pra fechar a janela.', True, BLACK)
    message_rect = message_text.get_rect(center=(screen_width // 2, screen_height // 2 - 50))

    button_rect = pygame.Rect(0, 0, 200, 50)  # Define tamanho do botão
    button_rect.center = (screen_width // 2, screen_height // 2 + 50)  # Centraliza o botão

    sound_file_path = Path(__file__).parent / "alert.wav"

    try:
        alert_sound = pygame.mixer.Sound(sound_file_path)
    except FileNotFoundError:
        alert_sound = None
        print(f"Som de alerta não encontrado: {sound_file_path}")

    if alert_sound:
        alert_sound.play()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.MOUSEBUTTONDOWN:
                if button_rect.collidepoint(event.pos):
                    delete_file(Path.home() / "Documents/aa.txt")
                    kill_process('alert_screen.exe')
                    running = False

        mouse_pos = pygame.mouse.get_pos()

        # Verifica se o mouse está sobre o botão
        if button_rect.collidepoint(mouse_pos):
            button_color = BUTTON_COLOR_HOVER
            text_color = WHITE
        else:
            button_color = BUTTON_COLOR_DEFAULT
            text_color = BLACK

        # Tela pisca entre cinza e amarelo
        screen.fill(GRAY)
        
        # Desenha o texto de aviso centralizado
        screen.blit(message_text, message_rect)

        # Desenha o botão centralizado
        pygame.draw.rect(screen, button_color, button_rect)
        text = button_font.render('OK', True, text_color)
        screen.blit(text, text.get_rect(center=button_rect.center))

        pygame.display.flip()
        pygame.time.wait(500)
        
        screen.fill(YELLOW)

        # Desenha o texto de aviso centralizado
        screen.blit(message_text, message_rect)

        # Desenha o botão centralizado
        pygame.draw.rect(screen, button_color, button_rect)
        screen.blit(text, text.get_rect(center=button_rect.center))
        
        pygame.display.flip()
        pygame.time.wait(500)

    if alert_sound:
        alert_sound.stop()

    pygame.quit()
    os._exit(0)

# Verifica se o disco C: está criptografado
if is_bitlocker_encrypted('C:'):
    show_alert_screen()