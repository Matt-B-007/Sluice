# SPDX-License-Identifier: GPL-3.0-or-later
"""0.13.1 (House Standard): signed updates. The checksum file of every release is signed with minisign; Sluice carries both
public keys and takes a signature from either. These tests write real minisign-format files with keys made for the test."""

import base64
import hashlib

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from sluice import signing, update_check, update_install  # noqa: E402
from test_update_install import FakeNet, SUM_URL, ZIP_URL, make_root, stage_it  # noqa: E402

SIG_URL = SUM_URL + ".minisig"


def make_key(key_id=b"\x01\x02\x03\x04\x05\x06\x07\x08"):
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public = base64.b64encode(b"Ed" + key_id + raw).decode()
    return private, key_id, public


def minisign(private, key_id, data: bytes, comment="Sluice v1.1.0", prehash=True) -> str:
    """What `minisign -S` writes (prehashed with BLAKE2b-512 by default, as minisign 0.10 and newer do)."""
    message = hashlib.blake2b(data, digest_size=64).digest() if prehash else data
    signature = private.sign(message)
    global_sig = private.sign(signature + comment.encode())
    return (
        f"untrusted comment: signature from minisign secret key\n"
        f"{base64.b64encode((b'ED' if prehash else b'Ed') + key_id + signature).decode()}\n"
        f"trusted comment: {comment}\n{base64.b64encode(global_sig).decode()}\n"
    )


def test_both_keys_are_carried_with_the_ids_minisign_shows():
    assert [k.shown_id for k in signing.keys()] == ["88D3683FED78B31C", "F37DFE946A2F6C4E"]
    assert set(signing.PUBLIC_KEYS) == {"primary", "backup"}


def test_a_good_signature_from_either_key_is_accepted_and_anything_else_is_not():
    first, second, stranger = make_key(b"AAAAAAAA"), make_key(b"BBBBBBBB"), make_key(b"CCCCCCCC")
    trusted = [signing.parse_public_key(first[2]), signing.parse_public_key(second[2])]
    data = b"abc123  sluice-v1.1.0.zip\n"
    for private, key_id, _ in (first, second):
        for prehash in (True, False):
            assert signing.verify(data, minisign(private, key_id, data, prehash=prehash), trusted)
    with pytest.raises(signing.SignatureError, match="key Sluice does not know"):
        signing.verify(data, minisign(stranger[0], stranger[1], data), trusted)
    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(data + b"x", minisign(first[0], first[1], data), trusted)
    good = minisign(first[0], first[1], data).splitlines()
    good[2] = "trusted comment: Sluice v9.9.9"  # the trusted comment cannot be changed either
    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(data, "\n".join(good), trusted)
    with pytest.raises(signing.SignatureError, match="format"):
        signing.verify(data, "not a signature", trusted)


def test_a_signature_from_a_key_with_sluices_id_but_another_secret_is_refused():
    impostor = make_key(signing.keys()[0].key_id)  # same ID as the real primary key, different key
    data = b"abc  sluice-v1.1.0.zip\n"
    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(data, minisign(impostor[0], impostor[1], data))


def _signed_net(tmp_path, monkeypatch, signature_for):
    net = FakeNet(tmp_path)
    texts = {SUM_URL: net.checksum_text, SIG_URL: signature_for(net.checksum_text.encode())}
    net.fetch_text = lambda url: net.fetched.append(url) or texts[url]
    return net


def signed_result():
    return update_check.UpdateResult(
        "available", "1.0.0", "1.1.0", "https://example.com/r", zip_url=ZIP_URL, checksum_url=SUM_URL, signature_url=SIG_URL
    )


def test_the_updater_installs_a_release_signed_with_a_trusted_key(tmp_path, monkeypatch):
    private, key_id, public = make_key()
    monkeypatch.setitem(signing.PUBLIC_KEYS, "backup", public)
    net = _signed_net(tmp_path, monkeypatch, lambda data: minisign(private, key_id, data))
    assert stage_it(make_root(tmp_path), net, signed_result()) == "1.1.0"
    assert SIG_URL in net.fetched


def test_the_updater_refuses_a_bad_signature_before_downloading_the_zip(tmp_path, monkeypatch):
    private, key_id, _ = make_key()  # not one of Sluice's keys
    net = _signed_net(tmp_path, monkeypatch, lambda data: minisign(private, key_id, data))
    with pytest.raises(update_install.UpdateError, match="signature is not valid"):
        stage_it(make_root(tmp_path), net, signed_result())
    assert ZIP_URL not in net.fetched


def test_an_unsigned_release_is_accepted_now_and_refused_once_signatures_are_required(tmp_path, monkeypatch):
    """0.13.1-beta.1 publishes signatures; the release after it requires them."""
    assert signing.REQUIRE_SIGNATURE is False
    assert stage_it(make_root(tmp_path), FakeNet(tmp_path)) == "1.1.0"
    monkeypatch.setattr(signing, "REQUIRE_SIGNATURE", True)
    other = tmp_path / "second"
    other.mkdir()
    with pytest.raises(update_install.UpdateError, match="not signed"):
        stage_it(make_root(other), FakeNet(other))


def test_the_check_finds_the_signature_and_a_missing_one_means_not_available_yet(monkeypatch):
    assets = [
        {"name": "sluice-v1.1.0.zip", "browser_download_url": ZIP_URL},
        {"name": "sluice-v1.1.0.zip.sha256", "browser_download_url": SUM_URL},
    ]
    release = {"tag_name": "v1.1.0", "html_url": "https://example.com/r", "assets": assets}
    found = update_check.check("1.0.0", url="https://example.com/api", fetch=lambda *a: release)
    assert found.status == "available" and found.signature_url == ""
    monkeypatch.setattr(signing, "REQUIRE_SIGNATURE", True)
    waiting = update_check.check("1.0.0", url="https://example.com/api", fetch=lambda *a: release)
    assert waiting.status == "up_to_date" and "not signed yet" in waiting.message
    assets.append({"name": "sluice-v1.1.0.zip.sha256.minisig", "browser_download_url": SIG_URL})
    signed = update_check.check("1.0.0", url="https://example.com/api", fetch=lambda *a: release)
    assert signed.status == "available" and signed.signature_url == SIG_URL


def test_the_release_workflow_signs_both_files_safely_and_checks_them_against_both_keys():
    from pathlib import Path

    workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml").read_text()
    steps = workflow.split("\n      - ")[1:]  # each step of the one job, as text (no YAML library needed)
    names = [step.split("\n")[0].removeprefix("name: ") for step in steps]
    for step in steps:  # the secret reaches a script only through env:, never inline in run:
        if "run: |" in step:
            assert "secrets." not in step.split("run: |", 1)[1], step.split("\n")[0]
    assert names[0].startswith("Check the signing key secret is set")  # fail fast, before anything is made
    sign = next(step for step in steps if step.startswith("name: Sign SHA256SUMS"))
    assert "MINISIGN_SECRET_KEY: ${{ secrets.MINISIGN_SECRET_KEY }}" in sign.split("run: |", 1)[0]
    assert 'chmod 600 "$key"' in sign and 'rm -f "$key"' in sign and "< /dev/null" in sign and '-t "Sluice ${TAG}"' in sign
    assert 'echo "$MINISIGN' not in workflow  # never printed
    check = next(i for i, step in enumerate(steps) if step.startswith("name: Check both signatures"))
    for key in signing.PUBLIC_KEYS.values():
        assert key in steps[check]
    assert check < next(i for i, step in enumerate(steps) if "softprops/action-gh-release" in step)  # before the draft
    assert "SHA256SUMS.minisig" in workflow and "zip.sha256.minisig" in workflow
