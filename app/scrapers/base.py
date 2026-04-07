import time
import logging
from abc import ABC, abstractmethod
from queue import Queue

logger = logging.getLogger(__name__)


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
    robots_txt_compliant: bool = True  # documenteer per subklasse
    request_delay_seconds: float = 2.0  # ethisch scrapen
    uses_types: bool = True  # False als scraper types intern negeert (bijv. Pararius geeft altijd alle typen)

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
