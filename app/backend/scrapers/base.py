import os
import time
import logging
import threading
import requests
from abc import ABC, abstractmethod
from queue import Queue

logger = logging.getLogger(__name__)

_FLARESOLVERR_URL = "http://byparr:8191/v1"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))  # max pagina's per scraper (Funda/Pararius/Kamernet); configureerbaar via .env


class BaseScraper(ABC):
    """
    Abstract base class voor alle Huursignal scrapers.

    Architectuurprincipes:
    - Stateless: geen instance-variabelen die tussen runs bewaard worden
    - Queue-based: resultaten gaan via een Queue, niet via return waarden
      (voorbereiding op Ray actors in Sprint 6)
    - Fault-isolated: exceptions worden gecatcht en gelogd, nooit gethrownd

    Ray migratie pad (Sprint 6):
      Huidige aanroep: scraper.scrape_to_queue(params, queue)
      Ray aanroep:     ray.remote(scraper.scrape_to_queue).remote(params, queue)
      Geen herschrijven nodig.

    Standaard listing schema (elke scraper MOET deze velden teruggeven):
      {
          "source":          str,   # scraper naam, bijv. "pararius"
          "url":             str,   # volledige unieke URL
          "external_id":     str,   # ID op bronsite indien beschikbaar, anders None
          "adres":           str,
          "stad":            str,
          "prijs":           int,   # per maand EUR, None als onbekend
          "oppervlakte":     int,   # m², None als onbekend
          "type_woning":     str,   # kamer/appartement/studio/etc., None als onbekend
          "foto_url":        str,   # eerste foto URL, None als geen
          "beschikbaar":     bool,  # altijd True bij scrapen
          "scraped_at":      str,   # ISO timestamp: datetime.utcnow().isoformat()
          "omschrijving":    str,   # volledige makelaarstekst, None als niet beschikbaar
          "rating":          float, # None totdat scoring geïmplementeerd is
          "rating_details":  dict,  # None totdat scoring geïmplementeerd is
      }
    """

    name: str = "base"
    category: str = "huurwoningen"  # groepering in admin dashboard
    robots_txt_compliant: bool = True  # documenteer per subklasse
    request_delay_seconds: float = 2.0  # ethisch scrapen
    uses_types: bool = True  # False als scraper types intern negeert (bijv. Pararius geeft altijd alle typen)
    flaresolverr_only: bool = False  # True als directe requests altijd geblokkeerd zijn (Funda, Pararius)
    allow_flaresolverr: bool = True   # False = nooit terugvallen op Byparr (bijv. kamernet: werkt direct, SPA haalt nooit 'networkidle')

    # Per-loop URL → HTML cache (class-level = gedeeld tussen alle scraper instanties)
    _cache: dict = {}
    _cache_lock: threading.Lock = threading.Lock()
    _stats: dict = {"direct": 0, "flare": 0, "cache": 0}
    _known_urls_cache: dict = {}  # source → set(url's al in DB); per loop geladen, gereset in clear_cache

    @classmethod
    def clear_cache(cls) -> None:
        """Leeg de URL-cache en reset statistieken. Aanroepen aan het begin van elke loop-iteratie."""
        with cls._cache_lock:
            BaseScraper._cache.clear()
            BaseScraper._stats = {"direct": 0, "flare": 0, "cache": 0}
            BaseScraper._known_urls_cache = {}

    @classmethod
    def flare_get(cls, url: str) -> str:
        """
        Haal HTML op met intelligente fallback en per-loop URL-caching.

        Volgorde:
        1. Cache check — geeft gecachede HTML terug als beschikbaar
        2. Direct request (max 3 pogingen) — tenzij cls.flaresolverr_only=True
        3. Byparr fallback — bij 403/429/Cloudflare detectie of verbindingsfout,
           tenzij cls.allow_flaresolverr=False (dan faalt het snel na de directe pogingen)

        Thread-safe via double-checked locking.
        Raises RuntimeError als zowel direct als Byparr mislukken.
        """
        # Stap 1: cache check
        with cls._cache_lock:
            if url in BaseScraper._cache:
                BaseScraper._stats["cache"] += 1
                logger.debug(f"[cache] Hit: {url[:80]}")
                return BaseScraper._cache[url]

        # Stap 2: direct request met retry (overgeslagen als scraper altijd geblokkeerd is)
        if not cls.flaresolverr_only:
            for attempt in range(3):
                try:
                    r = requests.get(url, timeout=15, headers={"User-Agent": _UA})
                    if r.status_code == 200 and "Just a moment" not in r.text:
                        html = r.text
                        with cls._cache_lock:
                            BaseScraper._stats["direct"] += 1
                            if url not in BaseScraper._cache:
                                BaseScraper._cache[url] = html
                        return html
                    logger.debug(f"[cache] Direct geblokkeerd (HTTP {r.status_code}), poging {attempt + 1}/3: {url[:60]}")
                except Exception as e:
                    logger.debug(f"[cache] Direct request mislukt ({e}), poging {attempt + 1}/3: {url[:60]}")
                if attempt < 2:
                    time.sleep(1)

        # Stap 2b: scrapers die expliciet geen Byparr-fallback willen (direct werkt; browser hangt op networkidle)
        if not cls.allow_flaresolverr:
            raise RuntimeError("Direct gefaald na 3 pogingen en Byparr-fallback uitgeschakeld voor deze scraper")

        # Stap 3: Byparr
        try:
            r = requests.post(_FLARESOLVERR_URL, json={
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,
            }, timeout=70)
            data = r.json()
            if data.get("status") != "ok":
                raise RuntimeError(f"Byparr fout: {data.get('message')}")
            html = data["solution"]["response"]
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Byparr verbindingsfout: {e}") from e

        with cls._cache_lock:
            BaseScraper._stats["flare"] += 1
            if url not in BaseScraper._cache:
                BaseScraper._cache[url] = html
        return html

    @classmethod
    def known_urls(cls, source: str) -> set:
        """
        Set van url's die al in de listings-tabel staan voor deze bron.
        Eénmalig per loop uit Supabase geladen en gecachet (gereset in clear_cache()).

        Gebruikt voor early-stop bij paginering: bij nieuwste-eerst betekent een
        pagina zonder nieuwe url's dat verdere pagina's ook niets nieuws bevatten.
        Bij een DB-fout valt het terug op een lege set → geen early-stop, gewoon
        tot MAX_PAGES doorscrapen.
        """
        with cls._cache_lock:
            if source in BaseScraper._known_urls_cache:
                return BaseScraper._known_urls_cache[source]
        try:
            from db import get_db
            # limit hoog genoeg voor de volledige bron; PostgREST geeft anders max 1000 rijen terug
            rows = (
                get_db().table("listings").select("url")
                .eq("source", source).limit(50000).execute().data
            ) or []
            urls = {r["url"] for r in rows if r.get("url")}
        except Exception as e:
            logger.warning(f"[{source}] known_urls: DB niet leesbaar ({e}); early-stop uitgeschakeld deze run")
            urls = set()
        with cls._cache_lock:
            BaseScraper._known_urls_cache[source] = urls
        return urls

    def _scrape_paginated(self, page_url_fn, parse_html_fn, source: str | None = None, seen_this_run: set | None = None) -> list[dict]:
        """
        Generieke paginering met early-stop voor scrapers die per pagina HTML ophalen.

        - page_url_fn(page_num) → url voor die pagina (pagina 1..MAX_PAGES, nieuwste eerst)
        - parse_html_fn(html)   → lijst listing-dicts (elk met "url")
        - source                → bron-naam voor known_urls (default self.name)
        - seen_this_run         → gedeelde set om over meerdere aanroepen heen te ontdubbelen
                                  (bijv. Kamernet dat per woningtype pagineert)

        Stopt zodra een pagina geen enkele nieuwe url oplevert (niet in DB én niet
        al deze run gezien) of leeg is, of bij een ophaalfout. Geeft de gecombineerde,
        binnen-run ontdubbelde lijst terug (zowel nieuwe als reeds bekende listings).
        """
        source = source or self.name
        known = self.known_urls(source)
        if seen_this_run is None:
            seen_this_run = set()
        results: list[dict] = []

        for page in range(1, MAX_PAGES + 1):
            url = page_url_fn(page)
            try:
                html = self.flare_get(url)
            except RuntimeError as e:
                logger.warning(f"[{self.name}] pagina {page} overgeslagen: {e}")
                break

            listings = parse_html_fn(html)
            if not listings:
                logger.info(f"[{self.name}] pagina {page}: geen listings, stoppen")
                break

            nieuw = 0
            for lst in listings:
                u = lst.get("url")
                if not u or u in seen_this_run:
                    continue
                seen_this_run.add(u)
                results.append(lst)
                if u not in known:
                    nieuw += 1

            logger.info(f"[{self.name}] pagina {page}/{MAX_PAGES}: {len(listings)} listings, {nieuw} nieuw")
            if nieuw == 0:
                logger.info(f"[{self.name}] pagina {page}: geen nieuwe listings — vroege stop")
                break

        return results

    def scrape(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
    ) -> list[dict]:
        """
        Publieke ingang met scheduler-guard. Directe aanroep (import, container-start,
        losse scripts) is geblokkeerd tenzij binnen run_scraper() of met FORCE_SCRAPE=true.
        De echte logica zit in _scrape_impl().
        """
        if os.getenv("FORCE_SCRAPE") != "true":
            from scheduler.scrape_scheduler import in_scheduler_context
            if not in_scheduler_context():
                raise RuntimeError(
                    f"Directe scrape geblokkeerd voor '{self.name}' — "
                    f"gebruik run_scraper() of zet FORCE_SCRAPE=true."
                )
        return self._scrape_impl(stad, min_prijs, max_prijs, types)

    @abstractmethod
    def _scrape_impl(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
    ) -> list[dict]:
        """
        Echte scrape-implementatie per scraper. Geeft listing-dicts terug volgens het
        standaard schema hierboven. Nooit een exception throwen — vang intern op en log.
        """
        ...

    def scrape_to_queue(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
        result_queue: Queue,
    ) -> None:
        """
        Queue-based wrapper voor Ray-compatibiliteit.
        Sprint 6: vervang Queue door ray.util.queue.Queue zonder verdere wijzigingen.
        """
        try:
            results = self._scrape_impl(stad, min_prijs, max_prijs, types)
            for listing in results:
                result_queue.put(listing)
        except Exception as e:
            logger.error(f"[{self.name}] Fatale fout in scrape_to_queue: {e}")

    def _retry(self, func, *args, max_attempts: int = 3, **kwargs):
        """Hulpfunctie voor retry met exponential backoff."""
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(
                    f"[{self.name}] Poging {attempt + 1} mislukt: {e}. Wacht {wait}s..."
                )
                time.sleep(wait)
        logger.error(f"[{self.name}] Alle {max_attempts} pogingen mislukt.")
        return None
