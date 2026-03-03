import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time

BASE_URL = "https://www.pararius.nl"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    url = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = uc.Chrome(
        options=options,
        headless=True,
        use_subprocess=False,
    )

    woningen = []

    try:
        print(f"[pararius] Ophalen: {url}", flush=True)
        driver.get(url)
        time.sleep(6)  # Cloudflare challenge tijd geven

        # Check of Cloudflare ons nog blokkeert
        if "Just a moment" in driver.title:
            print(f"[pararius] ⏳ Cloudflare challenge actief, nog 10 seconden wachten...", flush=True)
            time.sleep(10)

        print(f"[pararius] Paginatitel: {driver.title}", flush=True)

        items = driver.find_elements(By.CSS_SELECTOR, "li.search-list__item--listing")

        for item in items:
            try:
                titel_el = item.find_element(By.CSS_SELECTOR, ".listing-search-item__title")
                prijs_el = item.find_element(By.CSS_SELECTOR, ".listing-search-item__price")
                link_el  = item.find_element(By.CSS_SELECTOR, "a.listing-search-item__link--title")

                woningen.append({
                    'titel': titel_el.text.strip(),
                    'prijs': prijs_el.text.strip(),
                    'link': link_el.get_attribute("href"),
                    'bron': 'pararius.nl'
                })
            except:
                continue

        if len(woningen) == 0:
            print(f"[pararius] ⚠️ 0 woningen gevonden!", flush=True)
            print(f"[pararius] HTML snippet: {driver.page_source[:800]}", flush=True)
        else:
            print(f"[pararius] ✅ {len(woningen)} woningen gevonden", flush=True)

    except Exception as e:
        print(f"[pararius] ❌ Fout: {e}", flush=True)

    finally:
        driver.quit()

    return woningen
