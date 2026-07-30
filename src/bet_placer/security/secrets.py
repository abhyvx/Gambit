"""At-rest encryption for sensitive user fields (Stake API tokens)."""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache


def _raw_key() -> bytes:
    raw = (os.environ.get("GAMBIT_SECRETS_KEY") or "").strip()
    if not raw:
        raise RuntimeError("GAMBIT_SECRETS_KEY is required for encrypted secret storage")
    return hashlib.sha256(raw.encode("utf-8")).digest()


@lru_cache(maxsize=1)
def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    key = base64.urlsafe_b64encode(_raw_key())
    return Fernet(key)


def seal(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    text = str(plaintext)
    f = _fernet()
    if f is None:
        # ponytail: cryptography missing — prefix so we never confuse with ciphertext
        return f"plain:{text}"
    return "enc:" + f.encrypt(text.encode("utf-8")).decode("ascii")


def reveal(blob: str | None) -> str | None:
    if not blob:
        return None
    s = str(blob)
    if s.startswith("plain:"):
        return s[6:]
    if s.startswith("enc:"):
        f = _fernet()
        if f is None:
            raise RuntimeError("Encrypted secret present but cryptography is not installed")
        return f.decrypt(s[4:].encode("ascii")).decode("utf-8")
    # Legacy plaintext tokens
    return s
