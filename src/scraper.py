"""
Scraper de relojes reacondicionados de El Corte Ingles.
Usa Playwright para renderizar la pagina (evita bloqueos 403).
"""

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from notifier import send_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/watches.yaml")
SEEN_FILE = os.environ.get("SEEN_FILE", "/data/seen_watches.json")


def load_config() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        log.error("Config file not found: %s", CONFIG_PATH)
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def load_seen() -> set[str]:
    path = Path(SEEN_FILE)
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set[str]) -> None:
    Path(SEEN_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def product_id(name: str, price: str) -> str:
    return hashlib.sha256(f"{name}|{price}".encode()).hexdigest()[:16]


def scrape_watches(url: str) -> list[dict]:
    """Scrape the page using a headless browser and return product list."""
    products = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-ES",
        )
        page = context.new_page()
        log.info("Navigating to %s", url)
        page.goto(url, wait_until="networkidle", timeout=60_000)

        # Wait for product grid to load
        page.wait_for_timeout(3000)

        # El Corte Ingles uses several possible selectors for product cards.
        # We try multiple strategies.
        selectors = [
            "article.product-preview",
            "[data-product-id]",
            ".product_tile",
            ".grid-item .product",
            "li.product",
            ".plp-grid__item",
        ]

        cards = []
        for sel in selectors:
            cards = page.query_selector_all(sel)
            if cards:
                log.info("Found %d products with selector '%s'", len(cards), sel)
                break

        if not cards:
            # Fallback: try to extract from structured data (JSON-LD)
            json_ld = page.query_selector_all('script[type="application/ld+json"]')
            for script in json_ld:
                try:
                    data = json.loads(script.inner_text())
                    if isinstance(data, list):
                        for item in data:
                            if item.get("@type") == "Product":
                                products.append(_parse_json_ld(item))
                    elif data.get("@type") == "Product":
                        products.append(_parse_json_ld(data))
                except (json.JSONDecodeError, KeyError):
                    continue

            if not products:
                # Last resort: grab all visible text-based product info
                log.warning("No known selectors matched. Trying generic extraction.")
                products = _extract_generic(page)

            browser.close()
            return products

        for card in cards:
            try:
                name_el = card.query_selector(
                    "h2, h3, .product-preview__name, .product_tile-name, "
                    "[class*='name'], [class*='title'], a[title]"
                )
                price_el = card.query_selector(
                    ".product-preview__price, .product_tile-price, "
                    "[class*='price'], [data-price]"
                )
                link_el = card.query_selector("a[href]")

                name = ""
                if name_el:
                    name = name_el.inner_text().strip()
                    if not name:
                        name = name_el.get_attribute("title") or ""

                price = price_el.inner_text().strip() if price_el else "N/A"
                link = link_el.get_attribute("href") if link_el else ""
                if link and not link.startswith("http"):
                    link = f"https://www.elcorteingles.es{link}"

                if name:
                    products.append({"name": name, "price": price, "url": link})
            except Exception as e:
                log.debug("Error parsing card: %s", e)

        browser.close()

    log.info("Scraped %d products total", len(products))
    return products


def _parse_json_ld(item: dict) -> dict:
    offers = item.get("offers", {})
    price = offers.get("price", "N/A")
    currency = offers.get("priceCurrency", "EUR")
    return {
        "name": item.get("name", "Unknown"),
        "price": f"{price} {currency}" if price != "N/A" else "N/A",
        "url": item.get("url", ""),
    }


def _extract_generic(page) -> list[dict]:
    """Extract products by looking for common patterns in page content."""
    products = []
    all_links = page.query_selector_all("a[href*='/relojes-deportivos']")
    for link in all_links:
        text = link.inner_text().strip()
        href = link.get_attribute("href") or ""
        if text and len(text) > 5:
            if not href.startswith("http"):
                href = f"https://www.elcorteingles.es{href}"
            products.append({"name": text, "price": "N/A", "url": href})
    return products


def parse_price(price_str: str) -> float:
    """Extract numeric price from string like '299,99 EUR' or '299.99'."""
    cleaned = price_str.replace("EUR", "").replace("\u20ac", "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def matches_interest(product_name: str, watches: list[str]) -> bool:
    name_lower = product_name.lower()
    return any(w.lower() in name_lower for w in watches)


def run() -> None:
    config = load_config()
    url = config["url"]
    watches = config["watches"]
    max_price = config.get("max_price", 0)

    seen = load_seen()
    products = scrape_watches(url)

    new_matches = []
    for product in products:
        pid = product_id(product["name"], product["price"])
        if pid in seen:
            continue

        if matches_interest(product["name"], watches):
            price = parse_price(product["price"])
            if max_price > 0 and price > max_price:
                log.info("Skipping %s (price %.2f > max %.2f)", product["name"], price, max_price)
                continue
            new_matches.append(product)
            seen.add(pid)

    if new_matches:
        log.info("Found %d new matching watches!", len(new_matches))
        send_notification(new_matches)
    else:
        log.info("No new matching watches found.")

    save_seen(seen)


if __name__ == "__main__":
    run()
