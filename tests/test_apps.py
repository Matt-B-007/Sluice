# SPDX-License-Identifier: GPL-3.0-or-later
import os
import subprocess
import sys

from sluice.apps import AppEntry, Catalog, binary_from_exec, parse_desktop_file, steam_id_of_process
from sluice.backend import Stream
from sluice.model import Mixer


def desktop(path, **fields):
    fields = {"Type": "Application", **fields}
    lines = ["[Desktop Entry]"] + [f"{k}={v}" for k, v in fields.items()]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_exec_lines_become_binary_names():
    assert binary_from_exec("/usr/bin/firefox %u") == ("firefox", set())
    assert binary_from_exec("env GDK_BACKEND=x11 /opt/Discord/Discord --flag %U")[0] == "discord"
    assert binary_from_exec('"/opt/My App/bin/my-app" %F')[0] == "my-app"
    binary, extra = binary_from_exec("/usr/bin/flatpak run --branch=stable --command=obs com.obsproject.Studio @@u %u @@")
    assert binary == "obs" and "com.obsproject.studio" in extra
    assert binary_from_exec("/usr/bin/flatpak run org.mozilla.firefox")[0] == "firefox"
    assert binary_from_exec("") == ("", set())
    assert binary_from_exec("unbalanced 'quote") == ("", set())


def test_desktop_files(tmp_path):
    chrome = desktop(tmp_path / "google-chrome.desktop", Name="Google Chrome", Exec="/usr/bin/google-chrome-stable %U",
                     StartupWMClass="Google-chrome", Categories="Network;WebBrowser;")
    entry = parse_desktop_file(chrome)
    assert entry.name == "Google Chrome" and entry.key == "google-chrome-stable" and entry.kind == "app"
    assert {"google chrome", "google-chrome", "google-chrome-stable"} <= entry.aliases

    game = desktop(tmp_path / "supertux.desktop", Name="SuperTux", Exec="supertux2", Categories="Game;ArcadeGame;")
    assert parse_desktop_file(game).kind == "game"
    assert parse_desktop_file(desktop(tmp_path / "hidden.desktop", Name="X", Exec="x", NoDisplay="true")) is None
    assert parse_desktop_file(desktop(tmp_path / "link.desktop", Name="X", Exec="x", Type="Link")) is None
    assert parse_desktop_file(desktop(tmp_path / "noexec.desktop", Name="X")) is None
    shortcut = desktop(tmp_path / "hl2.desktop", Name="Half-Life 2", Exec="steam steam://rungameid/220")
    entry = parse_desktop_file(shortcut)
    assert (entry.key, entry.kind) == ("steam:220", "game")
    assert parse_desktop_file(desktop(tmp_path / "steam.desktop", Name="Steam", Exec="/usr/bin/steam %U")) is None


def make_steam(root):
    apps = root / "steamapps"
    apps.mkdir(parents=True)
    other = root.parent / "second-library"
    (other / "steamapps").mkdir(parents=True)
    (apps / "libraryfolders.vdf").write_text(f'"libraryfolders"\n{{\n "0"\n {{\n  "path"  "{root}"\n }}\n "1"\n {{\n  "path"  "{other}"\n }}\n}}\n')
    manifests = {apps: [(220, "Half-Life 2"), (1493710, "Proton Experimental"), (1628350, "Steam Linux Runtime 3.0 (sniper)")],
                 other / "steamapps": [(730, "Counter-Strike 2")]}
    for folder, items in manifests.items():
        for app_id, name in items:
            (folder / f"appmanifest_{app_id}.acf").write_text(f'"AppState"\n{{\n\t"appid"\t\t"{app_id}"\n\t"name"\t\t"{name}"\n}}\n')
    return root


def test_catalog_finds_steam_games_in_every_library_and_skips_tools(tmp_path):
    root = make_steam(tmp_path / "Steam")
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    desktop(apps_dir / "krita.desktop", Name="Krita", Exec="krita %F")
    desktop(apps_dir / "hl2.desktop", Name="Half-Life 2 (shortcut)", Exec="steam steam://rungameid/220")
    catalog = Catalog.scan(desktop_dirs=[apps_dir], steam_roots=[root, tmp_path / "missing"])
    names = [e.name for e in catalog.entries]
    assert names == ["Counter-Strike 2", "Half-Life 2", "Krita"]  # sorted; the manifest name wins; tools skipped
    assert catalog.label("steam:730") == "Counter-Strike 2"
    assert catalog.label("nothing") is None
    assert catalog.expand("steam:220") == {"steam:220", "half-life 2"}
    assert catalog.expand("unknown") == {"unknown"}


def test_scanning_a_missing_or_broken_setup_gives_an_empty_list_not_an_error(tmp_path):
    assert len(Catalog.scan(desktop_dirs=[tmp_path / "none"], steam_roots=[tmp_path / "none"])) == 0
    (tmp_path / "bad.desktop").write_bytes(b"\xff\xfe\x00[Desktop Entry]\nName=\xff\n")
    assert len(Catalog.scan(desktop_dirs=[tmp_path], steam_roots=[])) == 0


def test_a_stream_matches_by_any_of_its_names():
    chrome = Stream(1, "chrome", "Google Chrome", "sink", frozenset({"google chrome"}))
    mixer = Mixer.default()
    mixer.assign_app("google-chrome-stable", "music")
    assert mixer.channel_for_stream(chrome) is None                       # binary names differ, no catalog yet
    catalog = Catalog([AppEntry("Google Chrome", "google-chrome-stable", "app", frozenset({"google-chrome-stable", "google chrome"}))])
    assert mixer.channel_for_stream(chrome, catalog.expand).id == "music"  # same program by its app name
    mixer.assign_app("chrome", "game")
    assert mixer.channel_for_stream(chrome).id == "game"                   # a direct match needs no catalog


def test_steam_games_are_matched_by_game_id_and_assigned_by_it():
    proton = Stream(7, "wine64-preloader", "hl2.exe", "sink", frozenset({"steam:220", "hl2.exe"}))
    assert proton.assign_key == "steam:220"
    assert Stream(8, "firefox", "Firefox", "sink").assign_key == "firefox"
    mixer = Mixer.default()
    mixer.assign_app("steam:220", "game")
    assert mixer.channel_for_stream(proton).id == "game"
    other = Stream(9, "wine64-preloader", "other.exe", "sink", frozenset({"steam:730"}))
    assert mixer.channel_for_stream(other) is None  # same wine binary, different game


def test_steam_id_is_read_from_the_programs_environment():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             env={**os.environ, "SteamGameId": "220", "SteamAppId": "0"})
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], env={"PATH": os.environ["PATH"]})
    try:
        assert steam_id_of_process(child.pid) == "steam:220"
        assert steam_id_of_process(other.pid) is None
        assert steam_id_of_process(2 ** 22 + 12345) is None
        assert steam_id_of_process("junk") is None
    finally:
        child.kill()
        other.kill()
