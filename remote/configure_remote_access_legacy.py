import os
import subprocess
import time
from pathlib import Path

import psutil
import pyautogui
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

pyautogui.FAILSAFE = False

def configurar_remote():
    try:
        def verificar_chrome_aberto():
            for proc in psutil.process_iter():
                if 'chrome.exe' in proc.name():
                    return True
            return False

        if verificar_chrome_aberto():
            subprocess.run(["taskkill", "/f", "/im", "chrome.exe"])
            time.sleep(1)

        servico = Service(ChromeDriverManager().install()) 
        opcoes = Options()
        import win32con
        import win32gui

        hwnd = win32gui.FindWindow(None, "Google Chrome")
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)  # Esconde a janela
        opcoes.add_argument("--start-minimized")
        #opcoes.add_argument("--headless=new")

        navegador = webdriver.Chrome(service=servico, options=opcoes)
        navegador.set_window_position(-5000, 0)

        try:
            print("Realizando login no site do remote desktop...")
            navegador.get("https://remotedesktop.google.com/access")
        except Exception as e:
            print ("deu erro no link ")
        time.sleep(3)
        try:
            navegador.find_element(By.XPATH, "//input[@aria-label='E-mail ou telefone']").send_keys(os.environ["SERVICE_ACCOUNT_EMAIL"])
        except Exception as e:
            print (Exception), (e)
            print("erro em achar a porra do telefone")
        time.sleep(1)
        navegador.find_element(By.XPATH, "//span[text()='Avançar']").click()
        time.sleep(3)
        navegador.find_element(By.XPATH, "//input[@aria-label='Digite sua senha']").send_keys(os.environ["SERVICE_ACCOUNT_PASSWORD"])
        time.sleep(1)
        navegador.find_element(By.XPATH, "//span[text()='Avançar']").click()
        time.sleep(2)
        print("Configurando a máquina no remote desktop...")
        time.sleep(10)
        navegador.find_element(By.XPATH, "//span[text()='Set up via SSH']").click()
        print("Clicou no set up via ssh")
        time.sleep(3)
        navegador.find_element(By.XPATH, "//span[text()='Begin']/ancestor::div[@role='button']").click()
        print("Clicou no begin")
        time.sleep(3)

        wait = WebDriverWait(navegador, 20)

        time.sleep(3)

        botoes_next = navegador.find_elements(By.XPATH, "//div[@role='button' and @aria-label='Next']")

        botao_clicado = False
        for botao in botoes_next:
            texto = botao.text.strip()
            if texto == "Next":
                try:
                    navegador.execute_script("arguments[0].scrollIntoView();", botao)
                    navegador.execute_script("arguments[0].click();", botao)
                    print("Clicou no botão Next com texto visível")
                    botao_clicado = True
                    break
                except Exception as e:
                    print("Erro ao clicar no botão Next:", e)

        if not botao_clicado:
            print("Nenhum botão Next com texto visível foi clicado")
            raise Exception("Falha ao clicar no botão Next")
        
        try:
            print("Aguardando botão 'Authorize' aparecer...")
            authorize_btn = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//span[text()='Authorize']/ancestor::div[@role='button']"
            )))
            authorize_btn.click()
            print("Clicou no authorize")
        except Exception as e:
            print("Falha ao clicar no botão Authorize:", e)
            raise
        
        
        time.sleep(10)
        textarea_element = navegador.find_element(By.XPATH, "//textarea[@aria-label='Windows (PowerShell)']")
        conteudo_textarea = textarea_element.get_attribute("value")
        print("Conteúdo da textarea:", conteudo_textarea)

        pin = os.environ.get("CHROME_RD_PIN", input("Chrome Remote Desktop PIN: ").strip())
        usuario_windows = os.getlogin()

        print("Executando comando PowerShell para setar a máquina...")
        time.sleep(3)

        comando_powershell = f'& "${{Env:PROGRAMFILES(X86)}}\\Google\\Chrome Remote Desktop\\CurrentVersion\\remoting_start_host.exe" --code="{conteudo_textarea.split("--code=")[1].split(" --redirect-url")[0]}" --redirect-url="https://remotedesktop.google.com/_/oauthredirect" --name="{usuario_windows}" --pin="{pin}"'
        
        try:
            subprocess.run(["powershell", "-Command", comando_powershell], shell=True)
            print("Comando PowerShell executado com sucesso, fechando tudo...")
            resultado_remote = "Chrome remote desktop configurado com sucesso"
            time.sleep(3)
            
        except Exception as e:
            print("Erro ao executar o comando PowerShell:", e)
            resultado_remote = "Chrome remote desktop falhou"
        finally:
            navegador.quit()  
        time.sleep(10)              
        
        # Caminho do perfil padrão do Chrome
        perfil_chrome = str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")

        try:
            # Verifica se o diretório existe e apaga
            if os.path.exists(perfil_chrome):
                print(f"Apagando o perfil 'Default' do Chrome em: {perfil_chrome}")
                import shutil
                shutil.rmtree(perfil_chrome, ignore_errors=True)
                print("Perfil 'Default' apagado com sucesso.")
            else:
                print("Perfil 'Default' não encontrado. Nada foi apagado.")
        except Exception as e:
            print(f"Erro ao apagar o perfil 'Default': {e}")

        return resultado_remote
    
    except Exception as e:
        print("{resultado_remote}", e)
        return resultado_remote
    
configurar_remote()