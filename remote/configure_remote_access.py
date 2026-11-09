import os
import subprocess
import time

import psutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager


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
opcoes.add_argument("--start-minimized")

navegador = webdriver.Chrome(service=servico, options=opcoes)
navegador.set_window_position(-5000, 0)

print("Realizando login no site do remote desktop...")
navegador.get("https://remotedesktop.google.com/access")
time.sleep(3)
navegador.find_element(By.XPATH, '//*[@id="identifierId"]').send_keys(os.environ["SERVICE_ACCOUNT_EMAIL"])
time.sleep(1)
navegador.find_element(By.XPATH, '//*[@id="identifierNext"]/div/button/span').click()
time.sleep(3)
navegador.find_element(By.XPATH, '//*[@id="password"]/div[1]/div/div[1]/input').send_keys(os.environ["SERVICE_ACCOUNT_PASSWORD"])
time.sleep(1)
navegador.find_element(By.XPATH, '//*[@id="passwordNext"]/div/button/span').click()

print("Configurando a máquina no remote desktop...")
time.sleep(10)
navegador.find_element(By.XPATH, '//*[@id="yDmH0d"]/c-wiz/span/div/div[2]/div[1]/div[2]/div/div[4]/a/span[2]').click()
time.sleep(3)
navegador.find_element(By.XPATH, '//*[@id="yDmH0d"]/c-wiz[2]/span/div/div[2]/div[2]/section/div/div[2]/div/div/div/div[2]/span').click()
time.sleep(3)
navegador.find_element(By.XPATH, '//*[@id="yDmH0d"]/c-wiz[2]/span/div/div[2]/div[2]/section/div/div[2]/div/div/div/div[2]/span').click()
time.sleep(3)
navegador.find_element(By.XPATH, '//*[@id="yDmH0d"]/c-wiz[2]/span/div/div[2]/div[2]/section/div/div[2]/div/div/div/div[2]/span').click()
time.sleep(3)
textarea_element = navegador.find_element(By.XPATH, '//*[@id="yDmH0d"]/c-wiz[2]/span/div/div[2]/div[2]/section/div/div[2]/div/div/div/div[1]/div[3]/textarea')
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
    time.sleep(3)
except Exception as e:
    print("Erro ao executar o comando PowerShell:", e)
finally:
    navegador.quit()  