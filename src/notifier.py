"""
Sistema de notificaciones multi-canal.
Soporta: ntfy.sh (push notifications), Telegram, y log por consola.
Configurable via variables de entorno.
"""

import logging
import os
from urllib.request import Request, urlopen
from urllib.error import URLError
import json

log = logging.getLogger(__name__)

# --- ntfy.sh (recomendado para Arch Linux, auto-hosted o cloud) ---
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # e.g. "mis-relojes-garmin"

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_notification(products: list[dict]) -> None:
    """Send notification through all configured channels."""
    message = _build_message(products)
    sent = False

    if NTFY_TOPIC:
        sent = _send_ntfy(products, message) or sent

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        sent = _send_telegram(message) or sent

    if not sent:
        log.warning("No notification channel configured. Printing to stdout.")
        print("\n" + "=" * 60)
        print(message)
        print("=" * 60 + "\n")


def _build_message(products: list[dict]) -> str:
    lines = [f"🔔 {len(products)} reloj(es) encontrado(s) en El Corte Ingles!\n"]
    for p in products:
        lines.append(f"⌚ {p['name']}")
        lines.append(f"   💰 {p['price']}")
        if p.get("url"):
            lines.append(f"   🔗 {p['url']}")
        lines.append("")
    return "\n".join(lines)


def _send_ntfy(products: list[dict], message: str) -> bool:
    """Send push notification via ntfy.sh."""
    url = f"{NTFY_URL}/{NTFY_TOPIC}"
    title = f"{'⌚' * min(len(products), 3)} {len(products)} reloj(es) Garmin disponibles!"

    try:
        req = Request(url, data=message.encode("utf-8"), method="POST")
        req.add_header("Title", title)
        req.add_header("Priority", "high")
        req.add_header("Tags", "watch,garmin")

        # Add click URL for the first product
        if products and products[0].get("url"):
            req.add_header("Click", products[0]["url"])

        urlopen(req, timeout=10)
        log.info("ntfy notification sent to topic '%s'", NTFY_TOPIC)
        return True
    except URLError as e:
        log.error("Failed to send ntfy notification: %s", e)
        return False


def _send_telegram(message: str) -> bool:
    """Send message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    try:
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        urlopen(req, timeout=10)
        log.info("Telegram notification sent to chat %s", TELEGRAM_CHAT_ID)
        return True
    except URLError as e:
        log.error("Failed to send Telegram notification: %s", e)
        return False
