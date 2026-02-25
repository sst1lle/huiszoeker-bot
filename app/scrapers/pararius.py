import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pararius.nl"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    SITE_URL = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

    headers = {
        'User-Agent': 'Mozilla/5.0'
    }

    r = requests.get(SITE_URL, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')

    woningen = []

    for item in soup.select('li.search-list__item--listing'):
        titel_el = item.select_one('.listing-search-item__title')
        prijs_el = item.select_one('.listing-search-item__price')
        link_el  = item.select_one('a.listing-search-item__link--title')

        if not titel_el or not prijs_el or not link_el:
            continue

        titel = titel_el.text.strip()
        prijs = prijs_el.text.strip()
        link  = BASE_URL + link_el['href']

        woningen.append({
            'titel': titel,
            'prijs': prijs,
            'link': link,
            'bron': 'pararius.nl'
        })

    print(f'[pararius] {len(woningen)} woningen gevonden')
    return woningen
