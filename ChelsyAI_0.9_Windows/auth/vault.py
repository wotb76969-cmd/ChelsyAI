"""Per-user content keys (ТЗ SEC-03, SEC-04).

Every account has a random 256-bit data key (DEK). Private content (messages, conversation
titles, personal memory, files) is encrypted with AES-256-GCM under that DEK. The DEK itself is
never stored in clear; it exists only wrapped:

* ``pw_wrap``  — under a key derived from the user's password (Argon2id);
* ``rec_wrap`` — under a key derived from the user's recovery code (shown once to the user);
* per session  — under keys derived (HKDF) from the session's access and refresh secrets, which
  only the client holds. The Host stores only their hashes, so it cannot open a session's DEK
  without the client presenting its token.

Consequences:
* administrators of the application cannot read content: they hold none of these secrets;
* a password reset by an administrator removes ``pw_wrap``; old content stays readable only
  with the user's recovery code (there is no administrative escrow key);
* the Host process sees plaintext in memory while it works on a request (not end-to-end).
"""
from __future__ import annotations

import base64
import contextvars
import os
import secrets

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PREFIX = 'enc1:'
RECOVERY_ALPHABET = 'ABCDEFGHJKMNPQRSTVWXYZ23456789'      # no 0/O/1/I/L/U for dictation
LOCKED_TEXT = '[Содержимое зашифровано прежним ключом. Его можно открыть кодом восстановления в кабинете.]'

# The DEK of the account the current request acts for: (storage username, key version, dek).
CURRENT: contextvars.ContextVar = contextvars.ContextVar('chelsy_current_key', default=None)


class VaultError(Exception):
    pass


# ------------------------------------------------------------------ primitives
def new_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def kek_from_secret(secret: str, salt: bytes, params: dict | None = None) -> bytes:
    p = params or {'time_cost': 3, 'memory_cost': 65536, 'parallelism': 2}
    return hash_secret_raw(secret.encode('utf-8'), salt, time_cost=p['time_cost'], memory_cost=p['memory_cost'],
                           parallelism=p['parallelism'], hash_len=32, type=Type.ID)


def kek_from_token(token_secret: bytes, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'chelsy-session-' + purpose).derive(token_secret)


def wrap(kek: bytes, dek: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(kek).encrypt(nonce, dek, aad)


def unwrap(kek: bytes, blob: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(kek).decrypt(blob[:12], blob[12:], aad)
    except Exception as exc:          # InvalidTag and malformed blobs alike
        raise VaultError('wrong key') from exc


def new_recovery_code() -> str:
    raw = ''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(24))      # ~118 bits
    return '-'.join(raw[i:i + 4] for i in range(0, 24, 4))


def normalize_recovery_code(code: str) -> str:
    """Accept the code typed with spaces, without dashes or in lower case."""
    raw = ''.join(ch for ch in (code or '').upper() if ch in RECOVERY_ALPHABET)
    return '-'.join(raw[i:i + 4] for i in range(0, len(raw), 4))


# ------------------------------------------------------------------ content
def encrypt_text(dek: bytes, text: str, owner: str, version: int = 1) -> str:
    nonce = os.urandom(12)
    blob = nonce + AESGCM(dek).encrypt(nonce, text.encode('utf-8'), owner.encode('utf-8'))
    return f'{PREFIX}v{version}:' + base64.urlsafe_b64encode(blob).decode('ascii')


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def decrypt_text(dek: bytes, value: str, owner: str, version: int = 1) -> str:
    try:
        head, payload = value[len(PREFIX):].split(':', 1)
        if head != f'v{version}':
            return LOCKED_TEXT
        blob = base64.urlsafe_b64decode(payload.encode('ascii'))
        return AESGCM(dek).decrypt(blob[:12], blob[12:], owner.encode('utf-8')).decode('utf-8')
    except Exception:
        return LOCKED_TEXT


def seal(username: str, text):
    """Encrypt for storage when the current request holds this account's key; else unchanged."""
    current = CURRENT.get()
    if not isinstance(text, str) or not current or current[0] != username or is_encrypted(text):
        return text
    return encrypt_text(current[2], text, username, current[1])


def open_(username: str, value):
    """Decrypt a stored value for the account the current request acts for."""
    if not is_encrypted(value):
        return value
    current = CURRENT.get()
    if not current or current[0] != username:
        return LOCKED_TEXT
    return decrypt_text(current[2], value, username, current[1])


class acting_as:
    """Context manager: run code with this account's key available to the storage layer."""

    def __init__(self, username: str, dek: bytes | None, version: int = 1):
        self.value = (username, version, dek) if dek else None
        self.token = None

    def __enter__(self):
        self.token = CURRENT.set(self.value)
        return self

    def __exit__(self, *exc):
        CURRENT.reset(self.token)
        return False
