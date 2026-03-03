import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time


def scrape_huurwoningen(stad='den-haag', min_prijs=0, max_prijs=1200):
    url = f"https://www.huurwoningen.nl/in/{stad}/?price={min_prijs}-{max_prijs}"

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
        print(f"[huurwoningen] Ophalen: {url}", flush=True)
        driver.get(url)
        time.sleep(6)

        if "Just a moment" in driver.title:
            print(f"[huurwoningen] ⏳ Cloudflare challenge actief, nog 10 seconden wachten...", flush=True)
            time.sleep(10)

        print(f"[huurwoningen] Paginatitel: {driver.title}", flush=True)

        items = driver.find_elements(By.CSS_SELECTOR, "article.listing-search-item")

        for item in items:
            try:
                titel_el = item.find_element(By.CSS_SELECTOR, ".listing-search-item__title a")
                prijs_el = item.find_element(By.CSS_SELECTOR, ".listing-search-item__price")

                woningen.append({
                    "titel": titel_el.text.strip(),
                    "prijs": prijs_el.text.strip(),
                    "link": titel_el.get_attribute("href"),
                    "bron": "huurwoningen.nl"
                })
            except:
                continue

        if len(woningen) == 0:
            print(f"[huurwoningen] ⚠️ 0 woningen gevonden!", flush=True)
            print(f"[huurwoningen] HTML snippet: {driver.page_source[:800]}", flush=True)
        else:
            print(f"[huurwoningen] ✅ {len(woningen)} woningen gevonden.", flush=True)

    except Exception as e:
        print(f"[huurwoningen] ❌ Fout: {e}", flush=True)

    finally:
        driver.quit()

    return woningen
