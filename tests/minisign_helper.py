# SPDX-License-Identifier: GPL-3.0-or-later
"""Real minisign-format keys and signatures, made in the tests (0.13.1): what `minisign -G` and `minisign -S` write."""

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def make_key(key_id=b"\x01\x02\x03\x04\x05\x06\x07\x08"):
    """(private key, key id, public key text)."""
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, key_id, base64.b64encode(b"Ed" + key_id + raw).decode()


def minisign(private, key_id, data: bytes, comment="Sluice v1.1.0", prehash=True) -> str:
    """The text of a .minisig file for ``data`` (prehashed with BLAKE2b-512, minisign's default since 0.10)."""
    message = hashlib.blake2b(data, digest_size=64).digest() if prehash else data
    signature = private.sign(message)
    global_sig = private.sign(signature + comment.encode())
    return (
        "untrusted comment: signature from minisign secret key\n"
        f"{base64.b64encode((b'ED' if prehash else b'Ed') + key_id + signature).decode()}\n"
        f"trusted comment: {comment}\n{base64.b64encode(global_sig).decode()}\n"
    )
