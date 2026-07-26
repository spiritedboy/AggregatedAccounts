import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EncryptedField:
    ciphertext: bytes
    nonce: bytes
    tag: bytes
    version: int = 1


class CredentialCipher:
    """AES-256-GCM authenticated encryption with per-field random nonces."""

    def __init__(self, encoded_master_key: str) -> None:
        try:
            material = base64.b64decode(encoded_master_key, validate=True)
        except ValueError:
            material = encoded_master_key.encode()
        self._key = hashlib.sha256(material).digest()
        self._aes = AESGCM(self._key)

    def encrypt(self, plaintext: str, context: str) -> EncryptedField:
        nonce = os.urandom(12)
        combined = self._aes.encrypt(nonce, plaintext.encode(), context.encode())
        return EncryptedField(ciphertext=combined[:-16], nonce=nonce, tag=combined[-16:])

    def decrypt(self, field: EncryptedField, context: str) -> str:
        combined = field.ciphertext + field.tag
        return self._aes.decrypt(field.nonce, combined, context.encode()).decode()


def mask_identifier(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}••••{value[-2:]}"
    return f"{value[:4]}••••••••{value[-4:]}"
