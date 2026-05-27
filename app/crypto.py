"""
PRIVACY-FIX: Fernet symmetric encryption for PII fields (naam, telegram_chat_id, letter_text).

Key generation (run once, add to .env):
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If ENCRYPTION_KEY is absent, encrypt() is a no-op and data is stored plaintext.
safe_decrypt() handles both ciphertext and pre-encryption plaintext values so
migration is seamless — old rows display correctly without a bulk re-encrypt step.
"""
import os
import logging

logger = logging.getLogger(__name__)

_fernet = None
_warned = False


def _get_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    key = os.environ.get("ENCRYPTION_KEY", "").strip()
    if not key:
        if not _warned:
            logger.warning(
                "[crypto] ENCRYPTION_KEY niet ingesteld — PII-velden worden onversleuteld opgeslagen. "
                "Genereer een sleutel en voeg toe aan .env als ENCRYPTION_KEY=..."
            )
            _warned = True
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception as e:
        logger.error(f"[crypto] Ongeldig ENCRYPTION_KEY: {e}")
        return None


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a plaintext string. Returns plaintext unchanged if no key is configured."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a Fernet ciphertext. Raises InvalidToken if the input was never encrypted."""
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    if f is None:
        return ciphertext
    return f.decrypt(ciphertext.encode()).decode()


def safe_decrypt(value: str | None) -> str | None:
    """
    Decrypt value, falling back to returning it as-is on failure.
    Handles pre-encryption plaintext rows so old data keeps working after key rotation.
    """
    if not value:
        return value
    try:
        return decrypt(value)
    except Exception:
        # Pre-encryption plaintext value — return unchanged
        return value
