# ADR-001 — Scraper Architectuur

**Status:** Geaccepteerd
**Datum:** 2026-04-07
**Auteur:** Sam Stille

---

## Context

De Huursignal-bot begon als een script met twee losse functies (`scrape_pararius`, `scrape_kamernet`). Bij elke nieuwe bronsite moest `main.py` aangepast worden: een nieuwe import, een nieuwe dedup-dict, een nieuwe loop. Dat schaalt niet.

Sprint 4 introduceert een architectuurwijziging: van losse functies naar een plugin-systeem op basis van een abstracte basisklasse en auto-discovery via `importlib`.

---

## Beslissing

### 1. `BaseScraper` als abstracte basisklasse

Alle scrapers erven van `app/scrapers/base.py::BaseScraper` (ABC).

**Interface:**
```python
class BaseScraper(ABC):
    name: str                    # unieke scraper-identifier
    uses_types: bool = True      # False als scraper types intern negeert
    robots_txt_compliant: bool
    request_delay_seconds: float

    @abstractmethod
    def scrape(self, stad, min_prijs, max_prijs, types, radius_km=None) -> list[dict]: ...
    def scrape_to_queue(self, ..., result_queue: Queue) -> None: ...  # Ray-ready wrapper
    def _retry(self, func, *args, max_attempts=3, **kwargs): ...      # exponential backoff
```

**Waarom ABC en niet duck typing?**
Een scraper die `scrape()` niet implementeert crasht bij laden, niet bij de eerste scrape-run 's nachts. Vroeg falen is beter.

### 2. Auto-discovery via `importlib` + `inspect`

`main.py::load_scrapers()` itereert over alle modules in `app/scrapers/` met `pkgutil.iter_modules`, importeert elk bestand, en zoekt naar subklassen van `BaseScraper` via `inspect.getmembers`.

`base.py` wordt expliciet overgeslagen.

**Gevolg:** Een nieuwe scraper toevoegen vereist uitsluitend:
1. Een nieuw `.py`-bestand in `app/scrapers/`
2. Een klasse die `BaseScraper` erft

`main.py` hoeft nooit gewijzigd te worden. Dit is het Open/Closed principe in de praktijk.

### 3. `uses_types` class attribute

Pararius retourneert altijd alle woningtypes; de URL heeft geen type-filter. Kamernet scrapt per type een aparte URL.

In plaats van speciale logica in `main.py` per scraper, declareert elke scraper zelf zijn gedrag:

```python
class ParariusScraper(BaseScraper):
    uses_types = False  # URL heeft geen type-segment
```

`scrape_plan.bouw_scrape_taken()` gebruikt dit attribuut: voor `uses_types=False` scrapers wordt één taak per (site, stad) gescraped; voor Kamernet worden types geünioneerd over alle users die die stad zoeken. Geen per-user scrape-combinaties meer.

### 4. Scraper-configuratie in Supabase (`scraper_config`)

Scrapers kunnen aan/uit worden gezet via de admin-interface zonder de bot te herstarten. De bot registreert zichzelf bij opstart (`registreer_scrapers()`), de admin kan togglen via `/admin/scrapers`, en de bot filtert elke loop via `get_enabled_scrapers()`.

**Fail-open:** Bij een DB-fout worden alle scrapers als actief beschouwd.

### 5. `scrape_to_queue()` voor Ray-compatibiliteit (Sprint 6)

De huidige aanroep is synchroon. De `scrape_to_queue()` wrapper maakt een toekomstige migratie naar Ray actors triviaal:

| Nu | Sprint 6 |
|---|---|
| `scraper.scrape_to_queue(params, queue)` | `ray.remote(scraper.scrape_to_queue).remote(params, queue)` |

Geen herschrijven nodig.

---

## Overwogen alternatieven

### A. Entry points (setuptools plugins)
Standaard Python plugin-mechanisme. Vereist `setup.py` of `pyproject.toml` per scraper en `pip install -e .` na elke toevoeging. Te zwaar voor een intern project op een Raspberry Pi.

### B. Configuratiebestand met scraper-lijst
Een `scrapers.yml` met klassenamen die geladen worden. Vereist handmatige aanpassing bij elke nieuwe scraper — hetzelfde probleem als de oorspronkelijke hardcoded imports.

### C. Duck typing zonder ABC
Simpler, maar een scraper zonder `scrape()`-methode faalt pas bij runtime, 's nachts, stilzwijgend. De ABC geeft een duidelijke fout bij laden.

---

## Consequenties

**Positief:**
- Nieuwe scraper toevoegen = 1 bestand, geen andere wijzigingen
- Elke scraper is volledig geïsoleerd; een crash in één scraper stopt de anderen niet
- Admin kan scrapers aan/uit zetten zonder herstart
- Ray-migratie in Sprint 6 vereist minimale aanpassingen

**Negatief / aandachtspunten:**
- Auto-discovery laadt alle bestanden in `app/scrapers/` — zorg dat test- of experimentele scrapers daar niet in terechtkomen (gebruik `scripts/` of een aparte map)
- `uses_types=False` is een contract: de scraper belooft altijd alle types terug te geven. Als Pararius ooit een type-filter in de URL krijgt, moet dit attribuut en de dedup-sleutellogica aangepast worden
