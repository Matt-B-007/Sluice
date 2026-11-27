# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed updates (0.13.1, House Standard): every release's checksum files are signed with minisign. Sluice carries both public
keys (the main one and the backup) and accepts a signature from either. The check uses the ``cryptography`` package's Ed25519.

The minisign format, in short:
* a public key is base64 of ``b"Ed"`` + an 8-byte key ID + the 32-byte Ed25519 key;
* a ``.minisig`` file has four lines: an untrusted comment, base64 of the algorithm (``Ed``, or ``ED`` when the file was hashed
  with BLAKE2b-512 first, minisign's default) + the key ID + the 64-byte signature, then ``trusted comment: ...`` and base64 of
  a second signature over the first signature followed by the trusted comment, so the comment cannot be changed either.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

# 0.13.1-beta.1 published signatures but still took an unsigned release; from 0.13.1-beta.2 an update must carry a good
# signature from one of the two keys: one without is "not available yet", and one with a wrong signature is refused.
REQUIRE_SIGNATURE = True

PUBLIC_KEYS = {
    "primary": "RWQcs3jtP2jTiAMafwQX8UwciSjOH4o9tQcCVvYl2NkdnOeVupKPlhvC",  # key ID 88D3683FED78B31C
    "backup": "RWRObC9qlP598z1kmTFw7W+TKYKk3w2/63qWyRWkvRSkqGwGEgjmOlGe",  # key ID F37DFE946A2F6C4E
}


class SignatureError(Exception):
    """The signature is missing, malformed, from an unknown key, or does not match."""


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes
    key: bytes

    @property
    def shown_id(self) -> str:
        """The key ID as minisign prints it (the 8 bytes read as a little-endian number, in hex)."""
        return self.key_id[::-1].hex().upper()


def _b64(text: str, size: int, what: str) -> bytes:
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"{what} is not valid base64") from exc
    if len(raw) != size:
        raise SignatureError(f"{what} has the wrong length")
    return raw


def parse_public_key(text: str) -> PublicKey:
    raw = _b64(text, 42, "the public key")
    if raw[:2] != b"Ed":
        raise SignatureError("the public key is not an Ed25519 minisign key")
    return PublicKey(raw[2:10], raw[10:])


def keys() -> list:
    return [parse_public_key(text) for text in PUBLIC_KEYS.values()]


def available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("cryptography.hazmat.primitives.asymmetric.ed25519") is not None
    except ImportError:  # (find_spec imports the parent packages, and "cryptography" itself may be missing)
        return False


def verify(data: bytes, signature_file: str, trusted: list = None) -> str:
    """Check ``data`` against the text of a ``.minisig`` file. Returns which key signed it ("primary" or "backup") and raises
    SignatureError when it is not a good signature from one of ``trusted`` (default: Sluice's two keys)."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise SignatureError("the cryptography package is not installed, so the signature cannot be checked") from exc
    lines = [line.rstrip("\r") for line in signature_file.splitlines()]
    if len(lines) < 4 or not lines[0].startswith("untrusted comment:") or not lines[2].startswith("trusted comment: "):
        raise SignatureError("the signature file is not in minisign's format")
    sig = _b64(lines[1], 74, "the signature")
    algorithm, key_id, signature = sig[:2], sig[2:10], sig[10:]
    if algorithm == b"ED":
        message = hashlib.blake2b(data, digest_size=64).digest()
    elif algorithm == b"Ed":
        message = data
    else:
        raise SignatureError("the signature uses an algorithm Sluice does not know")
    comment = lines[2][len("trusted comment: ") :].encode("utf-8")
    global_sig = _b64(lines[3], 64, "the trusted comment's signature")
    names = dict(zip(PUBLIC_KEYS, keys())) if trusted is None else {f"key {k.shown_id}": k for k in trusted}
    for name, key in names.items():
        if key.key_id != key_id:
            continue
        public = Ed25519PublicKey.from_public_bytes(key.key)
        try:
            public.verify(signature, message)
            public.verify(global_sig, signature + comment)
        except InvalidSignature as exc:
            raise SignatureError("the signature does not match: the file was changed or not signed by Sluice's key") from exc
        return name
    raise SignatureError("the file was signed with a key Sluice does not know")
