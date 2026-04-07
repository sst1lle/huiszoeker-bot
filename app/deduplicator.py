import re
import hashlib
import logging

logger = logging.getLogger(__name__)

# Bronprioriteit bij duplicaten: lagere index = hogere prioriteit
_SOURCE_PRIORITY = ["pararius", "kamernet"]


def _normalize_adres(adres: str | None) -> str:
    """Normaliseer adres voor fingerprinting: lowercase, alleen letters/cijfers."""
    if not adres:
        return ""
    return re.sub(r"[^a-z0-9]", "", adres.lower())


def fingerprint(listing: dict) -> str | None:
    """
    MD5 hash van genormaliseerd adres + prijs.
    Geeft None als adres of prijs ontbreekt (niet dedupliceerbaar).
    """
    adres = _normalize_adres(listing.get("adres"))
    prijs = listing.get("prijs")
    if not adres or not prijs:
        return None
    raw = f"{adres}:{prijs}"
    return hashlib.md5(raw.encode()).hexdigest()


def _source_rank(listing: dict) -> int:
    src = listing.get("source", "")
    try:
        return _SOURCE_PRIORITY.index(src)
    except ValueError:
        return len(_SOURCE_PRIORITY)


class Deduplicator:
    """
    Cross-site duplicaatdetectie op basis van genormaliseerd adres + prijs.

    Gebruik:
        dedup = Deduplicator()
        uniek = dedup.deduplicate(listings)

    Bij een duplicaat wint de bron met de hoogste prioriteit (Pararius > Kamernet).
    Listings zonder adres of prijs worden nooit als duplicaat herkend en altijd bewaard.
    """

    def deduplicate(self, listings: list[dict]) -> list[dict]:
        """
        Verwijder cross-site duplicaten. Geeft de deduplicated lijst terug.
        De volgorde van de originele lijst blijft zoveel mogelijk intact.
        """
        seen: dict[str, dict] = {}  # fingerprint → bewaard listing

        for listing in listings:
            fp = fingerprint(listing)
            if fp is None:
                # Niet fingerprint-baar: altijd bewaren, unieke sleutel = url
                seen[listing.get("url", id(listing))] = listing
                continue

            if fp not in seen:
                seen[fp] = listing
            else:
                existing = seen[fp]
                # Houd de bron met hoogste prioriteit
                if _source_rank(listing) < _source_rank(existing):
                    logger.debug(
                        f"[deduplicator] Duplicaat: {listing.get('url')} vervangt "
                        f"{existing.get('url')} (hogere bronprioriteit)"
                    )
                    seen[fp] = listing
                else:
                    logger.debug(
                        f"[deduplicator] Duplicaat weggegooid: {listing.get('url')} "
                        f"(behouden: {existing.get('url')})"
                    )

        result = list(seen.values())
        removed = len(listings) - len(result)
        if removed:
            logger.info(f"[deduplicator] {removed} duplicaat/duplicaten verwijderd uit {len(listings)} listings")

        return result
