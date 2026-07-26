import os

import pytest
from cryptography.exceptions import InvalidTag

from app.security.credentials import CredentialCipher, EncryptedField, mask_identifier


def test_aes_gcm_roundtrip_and_random_nonce():
    cipher = CredentialCipher(os.environ["APP_ENCRYPTION_KEY"])
    first = cipher.encrypt("sensitive-value", "account:api_key")
    second = cipher.encrypt("sensitive-value", "account:api_key")
    assert first.ciphertext != second.ciphertext
    assert first.nonce != second.nonce
    assert cipher.decrypt(first, "account:api_key") == "sensitive-value"
    assert len(first.nonce) == 12
    assert len(first.tag) == 16


def test_aes_gcm_rejects_tampered_tag():
    cipher = CredentialCipher(os.environ["APP_ENCRYPTION_KEY"])
    encrypted = cipher.encrypt("secret", "context")
    tampered = EncryptedField(
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        tag=bytes([encrypted.tag[0] ^ 1]) + encrypted.tag[1:],
    )
    with pytest.raises(InvalidTag):
        cipher.decrypt(tampered, "context")


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        ("abcdefghijklmno", "abcd••••••••lmno"),
        ("abcdefgh", "ab••••gh"),
        ("", ""),
    ],
)
def test_identifier_masking(value, masked):
    assert mask_identifier(value) == masked
