"""Protocol v1 cryptographic primitives.

All secret material is bytes. Callers decide how secrets are persisted; this
module never writes keys or plaintext to disk.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_NPUBBYTES,
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
)
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def random_key() -> bytes:
    return os.urandom(32)


def encrypt(plaintext: bytes, key: bytes, *, aad: bytes = b"", nonce: bytes | None = None) -> tuple[bytes, bytes]:
    nonce = nonce or os.urandom(crypto_aead_xchacha20poly1305_ietf_NPUBBYTES)
    if len(nonce) != crypto_aead_xchacha20poly1305_ietf_NPUBBYTES:
        raise ValueError("XChaCha20-Poly1305 nonce must be 24 bytes")
    return nonce, crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, aad, nonce, key)


def decrypt(ciphertext: bytes, key: bytes, *, nonce: bytes, aad: bytes = b"") -> bytes:
    return crypto_aead_xchacha20poly1305_ietf_decrypt(ciphertext, aad, nonce, key)


def signing_keypair() -> tuple[bytes, bytes]:
    private = SigningKey.generate()
    return bytes(private), bytes(private.verify_key)


def sign(message: bytes, private_key: bytes) -> bytes:
    return SigningKey(private_key).sign(message).signature


def verify(message: bytes, signature: bytes, public_key: bytes) -> None:
    VerifyKey(public_key).verify(message, signature)


def box_keypair() -> tuple[bytes, bytes]:
    private = PrivateKey.generate()
    return bytes(private), bytes(private.public_key)


def wrap_key(key: bytes, public_key: bytes) -> bytes:
    return SealedBox(PublicKey(public_key)).encrypt(key)


def unwrap_key(wrapped: bytes, private_key: bytes) -> bytes:
    return SealedBox(PrivateKey(private_key)).decrypt(wrapped)


def hkdf(secret: bytes, *, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """Small RFC 5869 SHA-256 implementation used for scoped opaque refs."""
    prk = hmac.new(salt, secret, hashlib.sha256).digest()
    output = b""
    block = b""
    counter = 1
    while len(output) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def opaque_ref(identifier: str, workspace_key: bytes, *, kind: str) -> str:
    key = hkdf(workspace_key, salt=b"docmancer-protocol-v1", info=kind.encode("utf-8"))
    digest = hmac.new(key, identifier.encode("utf-8"), hashlib.sha256).digest()
    return f"{kind}_{b64encode(digest)}"


__all__ = [
    "b64decode", "b64encode", "box_keypair", "decrypt", "encrypt", "hkdf",
    "opaque_ref", "random_key", "sign", "signing_keypair", "unwrap_key",
    "verify", "wrap_key",
]
