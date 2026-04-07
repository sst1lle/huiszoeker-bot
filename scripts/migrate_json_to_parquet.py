"""
Migreer data/woningen.json naar de Parquet datalake.

Mapping oud → nieuw schema:
  titel  → adres       (bijv. "Studio Treilerweg" → "Studio Treilerweg")
  link   → url
  bron   → source      ("pararius.nl" → "pararius")
  prijs  → prijs (int) ("€ 920 per maand" → 920, "Prijs op aanvraag" → None)

Idempotentie: MD5-checksum van woningen.json wordt opgeslagen in
data/.woningen_migrated. Bij herhaald uitvoeren zonder bestandswijziging
wordt de migratie overgeslagen.

Gebruik:
    python scripts/migrate_json_to_parquet.py [--force] [--report]

Opties:
    --force    Voer migratie uit ook als checksum onveranderd is
    --report   Schrijf performance-resultaten naar docs/performance.md
"""

import sys
import json
import re
import hashlib
import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

# Voeg app/ toe aan sys.path zodat storage geïmporteerd kan worden.
# Lokaal: scripts/ zit naast app/, dus parent.parent / "app" = repo/app/
# Docker: COPY app /app → storage.py zit direct in /app (= parent.parent)
_REPO = Path(__file__).resolve().parent.parent
APP_DIR = next(
    (p for p in [_REPO / "app" / "backend", _REPO / "app", _REPO]
     if (p / "storage.py").exists()),
    _REPO / "app" / "backend",
)
sys.path.insert(0, str(APP_DIR))

from storage import ListingStorage  # noqa: E402

DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
DOCS_DIR  = Path(__file__).resolve().parent.parent / "docs"
WONINGEN_JSON  = DATA_DIR / "woningen.json"
CHECKSUM_FILE  = DATA_DIR / ".woningen_migrated"


def _parse_prijs(tekst: str) -> int | None:
    """Converteer prijsstring naar integer. "€ 1.345 per maand" → 1345."""
    if not tekst:
        return None
    cleaned = tekst.replace(".", "").replace(",", "")
    m = re.search(r"\d+", cleaned)
    return int(m.group()) if m else None


def _source_slug(bron: str) -> str:
    """'pararius.nl' → 'pararius'"""
    return bron.split(".")[0] if bron else "onbekend"


def _extract_external_id(url: str) -> str | None:
    """Haal Pararius hex-ID op uit URL ('03798255' etc.)"""
    try:
        parts = url.strip("/").split("/")
        for part in parts:
            if re.fullmatch(r"[a-f0-9]{8}", part, re.I):
                return part
    except Exception:
        pass
    return None


def _extract_adres(titel: str) -> str:
    """
    'Studio Treilerweg' → 'Treilerweg'
    Verwijder het type-prefix (eerste woord als het een type is).
    """
    type_prefixes = {"studio", "appartement", "kamer", "woning", "huis"}
    parts = titel.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() in type_prefixes:
        return parts[1]
    return titel


def _type_uit_titel(titel: str) -> str | None:
    type_map = {
        "studio": "studio",
        "appartement": "appartement",
        "kamer": "kamer",
        "woning": "appartement",
        "huis": "appartement",
    }
    eerste_woord = titel.split(" ")[0].lower()
    return type_map.get(eerste_woord)


def md5_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def al_gemigreerd(checksum: str) -> bool:
    if not CHECKSUM_FILE.exists():
        return False
    return CHECKSUM_FILE.read_text().strip() == checksum


def markeer_gemigreerd(checksum: str) -> None:
    CHECKSUM_FILE.write_text(checksum)


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.2f} MB"


def schrijf_rapport(metrics: dict) -> None:
    """Schrijf performance-resultaten naar docs/performance.md."""
    DOCS_DIR.mkdir(exist_ok=True)
    pad = DOCS_DIR / "performance.md"

    inhoud = f"""\
# Performance — Parquet migratie

Gegenereerd op: {metrics['timestamp']}
Uitgevoerd op: {metrics.get('platform', 'onbekend')}

## Migratie: woningen.json → Parquet

| Metriek | Waarde |
|---|---|
| Invoerbestand | `data/woningen.json` |
| JSON bestandsgrootte | {metrics['json_size']} |
| Aantal records in JSON | {metrics['records_totaal']} |
| Overgeslagen (geen URL) | {metrics['overgeslagen']} |
| Prijs onbekend | {metrics['prijs_onbekend']} |
| **Parquet bestandsgrootte** | **{metrics['parquet_size']}** |
| **Compressieverhouding** | **{metrics['compressie_ratio']}× kleiner** |
| Parsetijd (JSON → dicts) | {metrics['parse_tijd_ms']} ms |
| Schrijftijd (dicts → Parquet) | {metrics['schrijf_tijd_ms']} ms |
| **Totale tijd** | **{metrics['totaal_tijd_ms']} ms** |
| **Doorvoer** | **{metrics['rows_per_sec']} rijen/sec** |

## Toelichting

- **Compressieverhouding**: Parquet gebruikt kolomgewijze opslag + snappy-compressie.
  Bij tekstzware datasets (URLs, adressen) is een factor 3-10× gebruikelijk.
- **Parsetijd vs schrijftijd**: De schrijftijd omvat DataFrame-constructie, type-inferentie
  en Parquet-serialisatie via PyArrow. Bij grotere datasets domineert de schrijftijd.
- **Doorvoer**: Op een Raspberry Pi 5 met NVMe is 5.000-50.000 rijen/sec realistisch
  voor kleine datasets. Bottleneck is PyArrow-initialisatie (vaste overhead ~50ms),
  niet doorvoercapaciteit.

## Scrape-loop benchmark (referentie)

Wordt gevuld na eerste productiedraai:

| Metriek | Waarde |
|---|---|
| Pararius listings per run | — |
| Kamernet listings per run | — |
| Scrape tijd per site | — |
| Deduplicaten per run | — |
| Parquet snapshot grootte | — |
| Supabase upsert tijd | — |
"""
    pad.write_text(inhoud, encoding="utf-8")
    print(f"[migratie] 📄 Rapport geschreven naar {pad}")


def migreer(force: bool = False, report: bool = False) -> None:
    if not WONINGEN_JSON.exists():
        print(f"[migratie] ❌ Bestand niet gevonden: {WONINGEN_JSON}")
        sys.exit(1)

    checksum = md5_file(WONINGEN_JSON)
    json_size = WONINGEN_JSON.stat().st_size
    print(f"[migratie] Checksum woningen.json: {checksum} ({_fmt_bytes(json_size)})")

    if not force and al_gemigreerd(checksum):
        print("[migratie] ✅ Al gemigreerd (checksum onveranderd). Gebruik --force om opnieuw uit te voeren.")
        return

    # ── Fase 1: JSON inlezen + mappen ────────────────────────────────────────
    t0 = time.perf_counter()

    data = json.loads(WONINGEN_JSON.read_text(encoding="utf-8"))
    print(f"[migratie] {len(data)} records geladen uit woningen.json")

    scraped_at = datetime.now(timezone.utc).isoformat()
    listings = []
    overgeslagen = 0

    for record in data:
        link = record.get("link", "")
        if not link:
            overgeslagen += 1
            continue

        titel = record.get("titel", "")
        bron  = record.get("bron", "pararius.nl")

        listings.append({
            "source":         _source_slug(bron),
            "url":            link,
            "external_id":    _extract_external_id(link),
            "adres":          _extract_adres(titel),
            "stad":           None,
            "prijs":          _parse_prijs(record.get("prijs", "")),
            "oppervlakte":    None,
            "type_woning":    _type_uit_titel(titel),
            "foto_url":       None,
            "beschikbaar":    True,
            "scraped_at":     scraped_at,
            "omschrijving":   None,
            "rating":         None,
            "rating_details": None,
            "_migrated_from": "woningen.json",
        })

    t1 = time.perf_counter()
    parse_ms = (t1 - t0) * 1000

    # ── Fase 2: schrijven naar Parquet ────────────────────────────────────────
    storage = ListingStorage()
    geschreven = storage.save_listings(listings)

    t2 = time.perf_counter()
    schrijf_ms = (t2 - t1) * 1000
    totaal_ms  = (t2 - t0) * 1000

    # Parquet bestandsgrootte ophalen
    parquet_files = sorted(storage.listings_dir.rglob("run_*.parquet"))
    parquet_size_bytes = parquet_files[-1].stat().st_size if parquet_files else 0
    compressie = round(json_size / parquet_size_bytes, 1) if parquet_size_bytes else 0
    rows_per_sec = int(geschreven / (totaal_ms / 1000)) if totaal_ms > 0 else 0
    prijs_onbekend = sum(1 for l in listings if l["prijs"] is None)

    markeer_gemigreerd(checksum)

    print(
        f"[migratie] ✅ Klaar —\n"
        f"  Records:      {geschreven} geschreven, {overgeslagen} overgeslagen, {prijs_onbekend} zonder prijs\n"
        f"  Bestanden:    JSON {_fmt_bytes(json_size)} → Parquet {_fmt_bytes(parquet_size_bytes)} ({compressie}× kleiner)\n"
        f"  Timing:       parse {parse_ms:.0f}ms + schrijven {schrijf_ms:.0f}ms = {totaal_ms:.0f}ms totaal\n"
        f"  Doorvoer:     {rows_per_sec} rijen/sec"
    )

    if report:
        import platform
        schrijf_rapport({
            "timestamp":        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "platform":         platform.node() or platform.system(),
            "json_size":        _fmt_bytes(json_size),
            "records_totaal":   len(data),
            "overgeslagen":     overgeslagen,
            "prijs_onbekend":   prijs_onbekend,
            "parquet_size":     _fmt_bytes(parquet_size_bytes),
            "compressie_ratio": compressie,
            "parse_tijd_ms":    f"{parse_ms:.0f}",
            "schrijf_tijd_ms":  f"{schrijf_ms:.0f}",
            "totaal_tijd_ms":   f"{totaal_ms:.0f}",
            "rows_per_sec":     rows_per_sec,
        })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migreer woningen.json naar Parquet datalake")
    parser.add_argument("--force",  action="store_true", help="Forceer migratie ook als checksum onveranderd is")
    parser.add_argument("--report", action="store_true", help="Schrijf performance-resultaten naar docs/performance.md")
    args = parser.parse_args()
    migreer(force=args.force, report=args.report)
