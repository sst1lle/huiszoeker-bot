import requests
from bs4 import BeautifulSoup
import time


def scrape_huurwoningen(stad='den-haag', min_prijs=0, max_prijs=1200):
    url = f'https://www.huurwoningen.nl/in/{stad}/?price={min_prijs}-{max_prijs}'

    headers = {
        'User-Agent': 'Mozilla/5.0'
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f'[huurwoningen] fout: {e}')
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    woningen = []

    for item in soup.select('li.search-list__item section.listing-search-item'):
        try:
            titel_el = item.select_one('a.listing-search-item__link')
            prijs_el = item.select_one('.listing-search-item__price')

            if not titel_el or not prijs_el:
                continue

            titel = titel_el.text.strip()
            link = titel_el['href']
            prijs = prijs_el.text.strip()

            if not link.startswith('http'):
                link = 'https://www.huurwoningen.nl' + link

            woningen.append({
                'titel': titel,
                'prijs': prijs,
                'link': link,
                'bron': 'huurwoningen.nl'
            })

        except Exception:
            continue

    time.sleep(10)
    print(f'[huurwoningen] {len(woningen)} woningen gevonden')
    return woningen
