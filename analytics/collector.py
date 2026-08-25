from datetime import datetime
import os
import random
import time
from dotenv import load_dotenv
import psycopg2
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

# Configurações do Banco de Dados
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")


def conectar_banco():
  return psycopg2.connect(
      host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
  )


def salvar_dado_no_banco(multiplicador_bruto):
  """Salva a rodada no formato técnico padronizado"""
  conn = conectar_banco()
  cursor = conn.cursor()

  multiplicador_formatado = f"{float(multiplicador_bruto):.2f}x"
  timestamp_rodada = datetime.now()
  horario_formatado = timestamp_rodada.strftime("%H:%M:%S")

  try:
    cursor.execute(
        """
            INSERT INTO game_rounds (multiplier, crash_point, round_timestamp, source)
            VALUES (%s, %s, %s, %s)
        """,
        (
            float(multiplicador_bruto),
            float(multiplicador_bruto),
            timestamp_rodada,
            "chrome_stealth_collector",
        ),
    )
    conn.commit()
    print(
        f"[COLETA CHROME] Horário: {horario_formatado} | Multiplicador:"
        f" {multiplicador_formatado}"
    )
  except Exception as e:
    print(f"Erro ao salvar no banco: {e}")
    conn.rollback()
  finally:
    cursor.close()
    conn.close()


def iniciar_coletor_chrome():
  print("Configurando o Google Chrome em modo Stealth (Anti-Detecção)...")

  options = uc.ChromeOptions()
  # Se quiser rodar sem abrir a janela visualmente (em segundo plano), descomente a linha abaixo:
  # options.add_argument('--headless=new')

  options.add_argument("--disable-gpu")
  options.add_argument("--no-sandbox")
  options.add_argument("--disable-dev-shm-usage")

  # Inicializa o navegador Chrome camuflado
  driver = uc.Chrome(options=options, use_subprocess=True)

  try:
    # Substitua pela URL real da página do jogo/site que você está minerando
    url_alvo = "https://exemplo-da-casa-de-apostas.com"
    print(f"Acessando o site alvo: {url_alvo}")
    driver.get(url_alvo)

    # Pausa inicial para simular o tempo de carregamento humano da página
    time.sleep(random.uniform(5.0, 8.0))

    ultimo_multiplicador_registrado = None

    while True:
      try:
        # =========================================================================
        # AJUSTE AQUI: O seletor CSS ou XPath do elemento da tela onde aparece o multiplicador
        # =========================================================================
        # Exemplo simulado buscando um elemento na tela:
        # elemento = WebDriverWait(driver, 10).until(
        #     EC.presence_of_element_located((By.CSS_SELECTOR, ".class-do-multiplicador"))
        # )
        # valor_texto = elemento.text.replace('x', '').strip()
        # multiplicador_atual = float(valor_texto)

        # Simulação para testes do fluxo (remova e use o seletor real acima quando plugar na casa):
        multiplicador_atual = round(random.uniform(1.00, 10.00), 2)

        # Evita duplicar a mesma rodada caso o script leia mais rápido do que o jogo atualiza
        if multiplicador_atual != ultimo_multiplicador_registrado:
          salvar_dado_no_banco(multiplicador_atual)
          ultimo_multiplicador_registrado = multiplicador_atual

        # Jitter / Pausa orgânica entre as verificações para parecer humano
        time.sleep(random.uniform(3.0, 7.0))

      except Exception as inner_e:
        print(
            "Aguardando nova rodada ou elemento não visível no momento..."
            f" ({inner_e})"
        )
        time.sleep(5)

  except KeyboardInterrupt:
    print("\nEncerrando o coletor com segurança...")
  finally:
    driver.quit()


if __name__ == "__main__":
  iniciar_coletor_chrome()
