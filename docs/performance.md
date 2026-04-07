# Performance — Parquet migratie

> Dit bestand wordt automatisch overschreven met echte meetresultaten door:
> ```bash
> docker compose run --rm huiszoeker python scripts/migrate_json_to_parquet.py --force --report
> ```

---

## Migratie: woningen.json → Parquet

| Metriek | Waarde |
|---|---|
| Invoerbestand | `data/woningen.json` |
| JSON bestandsgrootte | — |
| Aantal records in JSON | — |
| Overgeslagen (geen URL) | — |
| Prijs onbekend | — |
| **Parquet bestandsgrootte** | **—** |
| **Compressieverhouding** | **—** |
| Parsetijd (JSON → dicts) | — ms |
| Schrijftijd (dicts → Parquet) | — ms |
| **Totale tijd** | **— ms** |
| **Doorvoer** | **— rijen/sec** |

## Wat wordt gemeten en waarom

**Parsetijd** — tijd om `woningen.json` te lezen en elk record te mappen naar het nieuwe schema (veldnormalisatie, prijsconversie, ID-extractie). Laat zien hoe zwaar de transformatielogica is.

**Schrijftijd** — tijd om de lijst dicts om te zetten naar een Pandas DataFrame en weg te schrijven als Parquet via PyArrow. Bevat een vaste overhead van ~50 ms voor PyArrow-initialisatie; schaalt daarna lineair met rijen.

**Compressieverhouding** — JSON is tekstueel en niet-gecomprimeerd. Parquet gebruikt kolomgewijze opslag + Snappy-compressie. Bij tekstzware datasets (URLs, adressen) is een factor 3–10× kleiner gebruikelijk.

**Doorvoer (rijen/sec)** — maatstaf voor schaalbaarheid. Op een Raspberry Pi 5 met NVMe is 5.000–50.000 rijen/sec realistisch voor kleine datasets. Bij scrape-snapshots (100–500 rijen per run) domineert de vaste overhead; doorvoer wordt relevanter bij bulk-migratieoperaties.

## Scrape-loop benchmark (referentie)

Wordt gevuld na eerste productiedraai op de Pi:

| Metriek | Waarde |
|---|---|
| Pararius listings per run | — |
| Kamernet listings per run | — |
| Scrapers uitvoertijd (totaal) | — |
| Cross-site duplicaten per run | — |
| Parquet snapshot grootte | — |
| Supabase upsert tijd (totaal) | — |
