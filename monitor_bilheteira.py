#!/usr/bin/env python3
"""
Monitoriza a pagina do jogo Portugal vs Dinamarca na bilheteira da FPF
e envia uma mensagem no Telegram quando o texto de disponibilidade mudar
(ex.: "Disponivel Brevemente" -> bilhetes disponiveis).

O site esta protegido pela Cloudflare e bloqueia pedidos HTTP simples
(ex. biblioteca `requests`), por isso usamos um browser headless real
(Playwright + Chromium) para carregar a pagina.

Uso:
    python monitor_bilheteira.py

Instalacao:
    pip install playwright requests
    playwright install chromium

Variaveis de ambiente necessarias:
    TELEGRAM_BOT_TOKEN  - token do bot (via @BotFather)
    TELEGRAM_CHAT_ID    - chat id para onde enviar a mensagem

Pensado para correr periodicamente via cron (Oracle Cloud VM) ou similar.
Recomenda-se um intervalo de pelo menos 2-3 minutos entre execucoes,
para nao sobrecarregar o site nem aumentar o risco de bloqueio.
"""

import os
import sys
import json
import logging
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://bilheteira.fpf.pt/"
STATE_FILE = Path(__file__).parent / "bilheteira_state.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# Palavras-chave que indicam que a bilheteira AINDA NAO abriu.
PENDING_MARKERS = [
    "disponível brevemente",
    "disponivel brevemente",
    "a anunciar em breve",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def fetch_page_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(URL, wait_until="networkidle", timeout=30000)
            return page.inner_text("body")
        finally:
            browser.close()


def extract_status(text: str) -> str:
    """
    Devolve um pequeno resumo de estado baseado no texto da pagina,
    para comparar entre execucoes.
    """
    lowered = text.lower()
    for marker in PENDING_MARKERS:
        if marker in lowered:
            return "PENDING"

    # Se nao encontrarmos nenhum marcador de "ainda nao abriu",
    # assumimos que o estado mudou (bilhetes podem estar disponiveis).
    return "CHANGED"


def load_previous_state() -> str | None:
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("status")
    except Exception:
        return None


def save_state(status: str) -> None:
    STATE_FILE.write_text(json.dumps({"status": status}), encoding="utf-8")


def send_telegram_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID nao definidos. Mensagem nao enviada.")
        return

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        api_url,
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error("Falha ao enviar mensagem Telegram: %s %s", resp.status_code, resp.text)
    else:
        log.info("Mensagem Telegram enviada.")


def main() -> int:
    if os.environ.get("FORCE_TEST_MESSAGE") == "true":
        log.info("FORCE_TEST_MESSAGE ativo: a enviar mensagem de teste, sem verificar a pagina.")
        send_telegram_message(
            "Teste do monitor da bilheteira FPF: se recebeste isto, o bot "
            "e os secrets estao configurados corretamente."
        )
        return 0

    try:
        text = fetch_page_text()
    except Exception as exc:
        log.error("Erro ao obter a pagina (Cloudflare pode ter bloqueado): %s", exc)
        return 1

    status = extract_status(text)
    previous = load_previous_state()

    log.info("Estado atual: %s (anterior: %s)", status, previous)

    if previous is not None and status != previous:
        message = (
            "ALERTA bilheteira FPF: a pagina do Portugal vs Dinamarca mudou!\n"
            f"Estado anterior: {previous}\n"
            f"Estado atual: {status}\n"
            f"{URL}"
        )
        send_telegram_message(message)
    elif previous is None:
        log.info("Primeira execucao, a guardar estado inicial sem notificar.")

    save_state(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
