from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time


def scrape_huurwoningen(stad='den-haag', min_prijs=0, max_prijs=1200):

    url = f"https://www.huurwoningen.nl/in/{stad}/?price={min_prijs}-{max_prijs}"

    options = Options()
    options.binary_location = "/usr/bin/chromium"
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--single-process")
    options.add_argument("--no-zygote")
    options.add_argument("--disable-software-rasterizer")

    service = Service("/usr/bin/chromedriver")

    driver = webdriver.Chrome(
        service=service,
        options=options
    )

    woningen = []

    try:
        driver.get(url)
        time.sleep(5)

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
            print(f"[huurwoningen] ⚠️ 0 woningen gevonden! Mogelijk geblokkeerd of HTML-structuur gewijzigd.", flush=True)
            print(f"[huurwoningen] ⚠️ Gebruikte URL: {url}", flush=True)
        else:
            print(f"[huurwoningen] ✅ {len(woningen)} woningen gevonden.", flush=True)

    except Exception as e:
        print(f"[huurwoningen] ❌ Fout: {e}", flush=True)

    finally:
        driver.quit()

    return woningen
