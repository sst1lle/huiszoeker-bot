import os
import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

DATALAKE_DIR = Path(os.environ.get("DATALAKE_PATH", "/app/datalake"))
LISTINGS_DIR = DATALAKE_DIR / "listings"


class ListingStorage:
    """
    Append-only Delta Lake opslag voor listing snapshots.

    Elke scrape-run schrijft één Parquet-bestand naar:
        /app/datalake/listings/year=YYYY/month=MM/day=DD/run_{timestamp}.parquet

    DuckDB leest over alle bestanden heen via glob — geen enkel bestand
    wordt ooit overschreven of verwijderd (append-only).

    Gebruik:
        storage = ListingStorage()
        storage.save_listings(listings)
        df = storage.query("SELECT * FROM listings WHERE stad = 'den-haag'")
    """

    def __init__(self, datalake_path: Path | None = None):
        self.listings_dir = (
            Path(datalake_path) / "listings" if datalake_path else LISTINGS_DIR
        )

    def _partition_path(self, dt: datetime) -> Path:
        return self.listings_dir / f"year={dt.year}" / f"month={dt.month:02d}" / f"day={dt.day:02d}"

    def save_listings(self, listings: list[dict]) -> int:
        """
        Schrijf listings als Parquet snapshot. Geeft aantal geschreven rijen terug.
        Maakt de datalake directory aan als die niet bestaat.
        """
        if not listings:
            return 0

        now = datetime.now(timezone.utc)
        partition = self._partition_path(now)
        partition.mkdir(parents=True, exist_ok=True)

        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        path = partition / f"run_{timestamp}.parquet"

        df = pd.DataFrame(listings)

        # Zorg dat alle standaard velden aanwezig zijn (vul None in als ontbreekt)
        for col in ("source", "url", "external_id", "adres", "stad", "prijs",
                    "oppervlakte", "type_woning", "foto_url", "beschikbaar",
                    "scraped_at", "omschrijving", "rating", "rating_details"):
            if col not in df.columns:
                df[col] = None

        df.to_parquet(path, index=False)
        logger.info(f"[storage] {len(df)} listings geschreven naar {path}")
        return len(df)

    def query(self, sql: str) -> pd.DataFrame:
        """
        Voer een DuckDB SQL-query uit over alle listing Parquet-bestanden.
        Gebruik 'listings' als tabelnaam in je query.

        Voorbeeld:
            df = storage.query(\"SELECT * FROM listings WHERE stad = 'den-haag' AND prijs <= 1200\")
        """
        glob = str(self.listings_dir / "**" / "*.parquet")
        con = duckdb.connect()
        try:
            con.execute(f"CREATE VIEW listings AS SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
            return con.execute(sql).df()
        finally:
            con.close()

    def latest_run(self) -> pd.DataFrame | None:
        """Geeft het meest recente Parquet-bestand terug als DataFrame."""
        files = sorted(self.listings_dir.rglob("run_*.parquet"))
        if not files:
            return None
        return pd.read_parquet(files[-1])

    def stats(self) -> dict:
        """Aantal bestanden en totaal rijen in de datalake."""
        files = list(self.listings_dir.rglob("run_*.parquet"))
        if not files:
            return {"files": 0, "rows": 0}
        try:
            df = self.query("SELECT COUNT(*) AS n FROM listings")
            rows = int(df["n"].iloc[0])
        except Exception:
            rows = 0
        return {"files": len(files), "rows": rows}
