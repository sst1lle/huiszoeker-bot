from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time

BASE_URL = "https://www.pararius.nl"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    url = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

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
    # Voorkom detectie als bot
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

    # Verberg dat het Selenium is
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    woningen = []

    try:
        print(f"[pararius] Ophalen: {url}", flush=True)
        driver.get(url)
        time.sleep(5)

        page_source_snippet = driver.page_source[:500]
        print(f"[pararius] HTML snippet: {page_source_snippet}", flush=True)

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
            print(f"[pararius] ⚠️ 0 woningen gevonden! Mogelijk geblokkeerd of HTML-structuur gewijzigd.", flush=True)
        else:
            print(f"[pararius] ✅ {len(woningen)} woningen gevonden", flush=True)

    except Exception as e:
        print(f"[pararius] ❌ Fout: {e}", flush=True)

    finally:
        driver.quit()

    return woningen
