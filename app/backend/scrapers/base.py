import time
import logging
import threading
import requests
from abc import ABC, abstractmethod
from queue import Queue

logger = logging.getLogger(__name__)

_FLARESOLVERR_URL = "http://flaresolverr:8191/v1"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


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

    # Per-loop URL → HTML cache (class-level = gedeeld tussen alle scraper instanties)
    _cache: dict = {}
    _cache_lock: threading.Lock = threading.Lock()
    _stats: dict = {"direct": 0, "flare": 0, "cache": 0}

    @classmethod
    def clear_cache(cls) -> None:
        """Leeg de URL-cache en reset statistieken. Aanroepen aan het begin van elke loop-iteratie."""
        with cls._cache_lock:
            BaseScraper._cache.clear()
            BaseScraper._stats = {"direct": 0, "flare": 0, "cache": 0}

    @classmethod
    def flare_get(cls, url: str) -> str:
        """
        Haal HTML op met intelligente fallback en per-loop URL-caching.

        Volgorde:
        1. Cache check — geeft gecachede HTML terug als beschikbaar
        2. Direct request — tenzij cls.flaresolverr_only=True
        3. FlareSolverr fallback — bij 403/429/Cloudflare detectie of verbindingsfout

        Thread-safe via double-checked locking.
        Raises RuntimeError als zowel direct als FlareSolverr mislukken.
        """
        # Stap 1: cache check
        with cls._cache_lock:
            if url in BaseScraper._cache:
                BaseScraper._stats["cache"] += 1
                logger.debug(f"[cache] Hit: {url[:80]}")
                return BaseScraper._cache[url]

        # Stap 2: direct request (overgeslagen als scraper altijd geblokkeerd is)
        if not cls.flaresolverr_only:
            try:
                r = requests.get(url, timeout=15, headers={"User-Agent": _UA})
                if r.status_code == 200 and "Just a moment" not in r.text:
                    html = r.text
                    with cls._cache_lock:
                        BaseScraper._stats["direct"] += 1
                        if url not in BaseScraper._cache:
                            BaseScraper._cache[url] = html
                    return html
                logger.debug(f"[cache] Direct geblokkeerd (HTTP {r.status_code}), FlareSolverr: {url[:60]}")
            except Exception as e:
                logger.debug(f"[cache] Direct request mislukt ({e}), FlareSolverr: {url[:60]}")

        # Stap 3: FlareSolverr
        try:
            r = requests.post(_FLARESOLVERR_URL, json={
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,
            }, timeout=70)
            data = r.json()
            if data.get("status") != "ok":
                raise RuntimeError(f"FlareSolverr fout: {data.get('message')}")
            html = data["solution"]["response"]
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"FlareSolverr verbindingsfout: {e}") from e

        with cls._cache_lock:
            BaseScraper._stats["flare"] += 1
            if url not in BaseScraper._cache:
                BaseScraper._cache[url] = html
        return html

    @abstractmethod
    def scrape(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
        radius_km: int | None = None,
    ) -> list[dict]:
        """
        Scrape listings voor gegeven parameters.
        Geeft lijst van listing-dicts terug volgens het standaard schema hierboven.
        Nooit een exception throwen — vang intern op en log.
        """
        ...

    def scrape_to_queue(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
        result_queue: Queue,
        radius_km: int | None = None,
    ) -> None:
        """
        Queue-based wrapper voor Ray-compatibiliteit.
        Sprint 6: vervang Queue door ray.util.queue.Queue zonder verdere wijzigingen.
        """
        try:
            results = self.scrape(stad, min_prijs, max_prijs, types, radius_km=radius_km)
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
