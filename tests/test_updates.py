# SPDX-License-Identifier: GPL-3.0-or-later
from sluice.updates import check, is_newer, parse_version


def test_version_parsing_and_comparison():
    assert parse_version("v0.3.10-beta") == (0, 3, 10)
    assert parse_version("garbage") == ()
    assert is_newer("0.3.10", "0.3.9") and is_newer("v1.0", "0.9.9") and is_newer("0.4", "0.3.9")
    assert not is_newer("0.3.2", "0.3.2") and not is_newer("0.3.1", "0.3.2") and not is_newer("junk", "0.3.2")
    assert not is_newer("0.3", "0.3.0")  # trailing zeros do not make a version newer


def test_nothing_is_contacted_when_no_address_is_set(monkeypatch):
    monkeypatch.delenv("SLUICE_UPDATE_URL", raising=False)
    monkeypatch.setattr("sluice.updates.RELEASE_URL", "")  # the shipped address is set once the project is on GitHub

    def forbidden(url, timeout):
        raise AssertionError("no request may be made")

    assert check("0.3.2", fetch=forbidden).status == "not_configured"


def test_outcomes():
    github = lambda url, t: {"tag_name": "v0.4.0", "html_url": "https://example.org/releases/0.4.0"}  # noqa: E731
    result = check("0.3.2", url="https://example.org/latest", fetch=github)
    assert (result.status, result.latest, result.page) == ("available", "0.4.0", "https://example.org/releases/0.4.0")
    custom = lambda url, t: {"version": "0.3.2", "url": "https://example.org"}  # noqa: E731
    assert check("0.3.2", url="https://example.org/x", fetch=custom).status == "up_to_date"
    unsafe = lambda url, t: {"tag_name": "9.0", "html_url": "javascript:alert(1)"}  # noqa: E731
    assert check("0.3.2", url="https://example.org/x", fetch=unsafe).page == ""  # only https links are offered
    assert check("0.3.2", url="https://example.org/x", fetch=lambda u, t: {"tag_name": "soon"}).status == "error"

    def offline(url, timeout):
        raise OSError("network is unreachable")

    result = check("0.3.2", url="https://example.org/x", fetch=offline)
    assert result.status == "error" and "unreachable" in result.message


def test_a_non_https_address_is_refused():
    result = check("0.3.2", url="file:///etc/passwd")
    assert result.status == "error" and "https" in result.message


def test_a_list_of_releases_uses_the_newest_that_is_not_a_draft():
    releases = [
        {"tag_name": "v9.9.9", "html_url": "https://example.com/draft", "draft": True},
        {"tag_name": "v0.7.0", "html_url": "https://example.com/beta", "prerelease": True},
        {"tag_name": "v0.6.0", "html_url": "https://example.com/old"},
    ]
    result = check("0.6.10", url="https://x.example/releases", fetch=lambda url, timeout: releases)
    assert result.status == "available" and result.latest == "0.7.0" and result.page == "https://example.com/beta"
    again = check("0.7.0", url="https://x.example/releases", fetch=lambda url, timeout: releases)
    assert again.status == "up_to_date"
    empty = check("0.6.10", url="https://x.example/releases", fetch=lambda url, timeout: [])
    assert empty.status == "error" and "no releases" in empty.message


def test_the_shipped_update_address_is_https_and_points_at_the_release_list():
    from sluice import updates

    assert updates.RELEASE_URL.startswith("https://api.github.com/repos/") and updates.RELEASE_URL.endswith("/releases?per_page=5")


def test_the_notes_of_a_newer_release_come_with_the_answer_and_only_then():
    release = {"tag_name": "v9.0.0", "html_url": "https://example.com/r", "body": "  - **Big news.**\n"}
    newer = check("0.8.0", url="https://x.example/releases", fetch=lambda url, timeout: [release])
    assert newer.status == "available" and newer.notes == "- **Big news.**"
    same = check("9.0.0", url="https://x.example/releases", fetch=lambda url, timeout: [release])
    assert same.status == "up_to_date" and same.notes == ""
    long = dict(release, body="x" * 20000)
    assert len(check("0.8.0", url="https://x.example/releases", fetch=lambda url, timeout: [long]).notes) == 4000
    none = dict(release)
    del none["body"]
    assert check("0.8.0", url="https://x.example/releases", fetch=lambda url, timeout: [none]).notes == ""
