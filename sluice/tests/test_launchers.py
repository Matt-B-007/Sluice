# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sqlite3

from sluice.apps import Catalog, bottles_programs, legendary_games, lutris_games


def make_lutris(home):
    data = home / ".local" / "share" / "lutris"
    data.mkdir(parents=True)
    db = sqlite3.connect(data / "pga.db")
    db.execute("CREATE TABLE games (id INTEGER, name TEXT, slug TEXT, installed INTEGER, configpath TEXT)")
    db.execute("INSERT INTO games VALUES (1, 'Hades', 'hades', 1, 'hades-1650')")
    db.execute("INSERT INTO games VALUES (2, 'Not Installed', 'nope', 0, 'nope-1')")
    db.commit()
    db.close()
    games = home / ".config" / "lutris" / "games"
    games.mkdir(parents=True)
    (games / "hades-1650.yml").write_text("game:\n  exe: /games/Hades/x64/Hades.exe\n  prefix: /games/prefix\n")


def test_lutris_games_are_found_by_title_and_program_name(tmp_path):
    make_lutris(tmp_path)
    found = list(lutris_games(tmp_path))
    assert [e.name for e in found] == ["Hades"]
    assert {"lutris:hades", "hades", "hades.exe"} <= found[0].aliases


def test_epic_games_from_legendary_and_heroic(tmp_path):
    folder = tmp_path / ".config" / "heroic" / "legendaryConfig" / "legendary"
    folder.mkdir(parents=True)
    (folder / "installed.json").write_text(json.dumps({"Sugar": {"title": "Rocket League", "executable": "Binaries/Win64/RocketLeague.exe"}}))
    found = list(legendary_games(tmp_path))
    assert found[0].name == "Rocket League" and "rocketleague.exe" in found[0].aliases


def test_bottles_programs(tmp_path):
    bottle = tmp_path / ".local" / "share" / "bottles" / "bottles" / "Gaming"
    bottle.mkdir(parents=True)
    (bottle / "bottle.yml").write_text(
        "Name: Gaming\nExternal_Programs:\n  abc:\n    name: Notepad++\n    executable: notepad++.exe\n    path: C:\\Program Files\\Notepad++\\notepad++.exe\n")
    found = list(bottles_programs(tmp_path))
    assert [e.name for e in found] == ["Notepad++"] and "notepad++.exe" in found[0].aliases


def test_the_catalog_includes_them_and_survives_broken_files(tmp_path):
    make_lutris(tmp_path)
    (tmp_path / ".config" / "legendary").mkdir(parents=True)
    (tmp_path / ".config" / "legendary" / "installed.json").write_text("{ not json")
    catalog = Catalog.scan(desktop_dirs=[], steam_roots=[], home=tmp_path)
    assert catalog.label("lutris:hades") == "Hades"
    assert "hades.exe" in catalog.expand("lutris:hades")
