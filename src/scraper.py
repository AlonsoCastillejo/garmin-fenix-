"""
Scraper de relojes Garmin reacondicionados de El Corte Ingles.
Ejecutar: python scraper.py
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright


URL = "https://www.elcorteingles.es/deportes/reacondicionados/relojes-deportivos-y-smartwatch/8/"


def scrape_watches() -> list[dict]:
    """Scrape the page with a headless browser and return all products."""
    products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-ES",
        )
        page = context.new_page()

        print(f"Accediendo a {URL} ...")
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(5000)

        # Debug: save page content to understand the structure
        html = page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Pagina guardada en debug_page.html ({len(html)} chars)")

        # Try to find the page title to confirm we loaded correctly
        title = page.title()
        print(f"Titulo de la pagina: {title}")

        # Take a screenshot for debugging
        page.screenshot(path="debug_screenshot.png", full_page=True)
        print("Screenshot guardado en debug_screenshot.png")

        # --- Strategy 1: JSON-LD structured data ---
        json_ld_scripts = page.query_selector_all('script[type="application/ld+json"]')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.inner_text())
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        prod = item.get("item", item)
                        if prod.get("@type") == "Product":
                            products.append(_parse_jsonld_product(prod))
                elif isinstance(data, dict) and data.get("@type") == "Product":
                    products.append(_parse_jsonld_product(data))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            products.append(_parse_jsonld_product(item))
            except (json.JSONDecodeError, KeyError):
                continue

        if products:
            print(f"Encontrados {len(products)} productos via JSON-LD")
            browser.close()
            return products

        # --- Strategy 2: Common CSS selectors ---
        selectors = [
            "article.product-preview",
            "[data-product-id]",
            ".product_tile",
            ".product-list-item",
            "li[data-product]",
            ".plp-grid__item",
            ".grid-item",
            ".product-card",
            "[class*='product'][class*='card']",
            "[class*='product'][class*='tile']",
            "[class*='product'][class*='item']",
        ]

        cards = []
        for sel in selectors:
            cards = page.query_selector_all(sel)
            if cards:
                print(f"Encontrados {len(cards)} productos con selector '{sel}'")
                break

        if cards:
            for card in cards:
                product = _parse_card(card)
                if product:
                    products.append(product)
        else:
            # --- Strategy 3: Find all links that look like product pages ---
            print("No se encontraron selectores conocidos. Buscando enlaces de productos...")
            products = _extract_from_links(page)

        browser.close()

    return products


def _parse_jsonld_product(data: dict) -> dict:
    offers = data.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price", offers.get("lowPrice", "N/A"))
    currency = offers.get("priceCurrency", "EUR")
    return {
        "name": data.get("name", "Desconocido"),
        "price": f"{price} {currency}" if price != "N/A" else "N/A",
        "url": data.get("url", ""),
        "brand": data.get("brand", {}).get("name", ""),
        "image": data.get("image", ""),
    }


def _parse_card(card) -> dict | None:
    """Extract product info from a DOM card element."""
    name_el = card.query_selector(
        "h2, h3, h4, "
        "[class*='name'], [class*='title'], "
        "a[title], "
        "[class*='description']"
    )
    price_el = card.query_selector(
        "[class*='price'], [data-price], "
        "[class*='amount'], [class*='cost']"
    )
    link_el = card.query_selector("a[href]")

    name = ""
    if name_el:
        name = name_el.inner_text().strip()
        if not name:
            name = name_el.get_attribute("title") or ""
    if not name and link_el:
        name = link_el.get_attribute("title") or link_el.inner_text().strip()

    if not name:
        return None

    price = price_el.inner_text().strip() if price_el else "N/A"
    link = link_el.get_attribute("href") if link_el else ""
    if link and not link.startswith("http"):
        link = f"https://www.elcorteingles.es{link}"

    return {"name": name, "price": price, "url": link, "brand": "", "image": ""}


def _extract_from_links(page) -> list[dict]:
    """Fallback: extract from all links that look like product URLs."""
    products = []
    seen_names = set()
    links = page.query_selector_all("a[href]")
    for link in links:
        href = link.get_attribute("href") or ""
        text = link.inner_text().strip()
        # Product URLs on ECI usually contain /deportes/ or /p/
        if text and len(text) > 10 and ("/p/" in href or "/mp/" in href):
            if text not in seen_names:
                seen_names.add(text)
                if not href.startswith("http"):
                    href = f"https://www.elcorteingles.es{href}"
                products.append({"name": text, "price": "N/A", "url": href, "brand": "", "image": ""})
    return products


def filter_garmin(products: list[dict]) -> list[dict]:
    """Filter only Garmin watches."""
    return [
        p for p in products
        if "garmin" in p["name"].lower() or "garmin" in p.get("brand", "").lower()
    ]


def display_results(all_products: list[dict], garmin_products: list[dict]) -> None:
    print("\n" + "=" * 70)
    print(f"TOTAL RELOJES EN LA PAGINA: {len(all_products)}")
    print(f"RELOJES GARMIN: {len(garmin_products)}")
    print("=" * 70)

    if not garmin_products:
        print("\nNo se encontraron relojes Garmin reacondicionados.")
        return

    # Group by model
    models: dict[str, list[dict]] = {}
    for p in garmin_products:
        # Extract model name (simplify)
        name = p["name"]
        model = name  # keep full name as model key
        models.setdefault(model, []).append(p)

    print(f"\nMODELOS GARMIN ENCONTRADOS: {len(models)}")
    print("-" * 70)

    for i, (model, items) in enumerate(sorted(models.items()), 1):
        item = items[0]
        print(f"\n  {i}. {model}")
        print(f"     Precio: {item['price']}")
        if item.get("url"):
            print(f"     URL: {item['url']}")

    print("\n" + "=" * 70)


def main():
    products = scrape_watches()

    if not products:
        print("\nNo se pudieron extraer productos. Revisa debug_page.html y debug_screenshot.png")
        sys.exit(1)

    garmin = filter_garmin(products)
    display_results(products, garmin)


if __name__ == "__main__":
    main()
