# Developing Sluice

How to run Sluice from a checkout, how the code is laid out and how to publish it. The user guide is the main [README](../README.md).

## Publishing

See [PUBLISHING.md](PUBLISHING.md) for the step-by-step guide. The repository includes continuous
integration, a release workflow and issue templates.

## Running it

```bash
pip install -e ".[dev]"
pytest                                                    # more than 1,000 tests, no audio server needed
QT_QPA_PLATFORM=offscreen sluice --demo --screenshot out.png
```

| File | Role |
|---|---|
| `sluice/model.py` | channels, mixes, gain/mute/link logic, saving (no Qt, no audio) |
| `sluice/dsp.py` | the real-time mixing graph and limiter |
| `sluice/effects.py` | built-in effects and VST3 hosting (pedalboard) |
| `sluice/audio_io.py` | JACK audio client, plus a synthetic one for demo and tests |
| `sluice/linker.py` | `pw-link` wrapper, and the watcher that tells Sluice when the PipeWire graph changed |
| `sluice/backend.py` | PulseAudio control: devices, virtual sinks, moving apps (and a fake for tests) |
| `sluice/engine.py` | keeps everything above in sync with the model |
| `sluice/__main__.py`, `sluice/__init__.py` | start-up, the command-line flags, the version |
| `sluice/ui.py` | the one place the rest of Sluice imports the window and its parts from (it re-exports the five modules below) |
| `sluice/ui_base.py` | sizes, names, small helpers and small widgets (typed-value boxes, double-click-reset sliders) shared by the cards |
| `sluice/ui_meters.py` | the level meter, the fader with its taper, the source picture and the Nexus ring |
| `sluice/ui_channel.py`, `sluice/ui_mix.py` | the channel cards (Columns and Rows) and the Listen, Broadcast and Recording cards |
| `sluice/ui_window.py` | the main window: the top bar, the layouts, the meter timer, saving |
| `sluice/ui_menus.py`, `ui_themes.py`, `ui_tray.py`, `ui_updating.py` | parts of the main window: the menus, the themes, the tray icon and updating in place (`MainWindow` inherits them) |
| `sluice/ui_settings.py` | the Settings window (bound to the same actions as the menus) |
| `sluice/depth.py` | depth colours worked out from any theme: keys, glass, shadows, grooves, trays, channel colours on light themes |
| `sluice/skin_tile.py`, `ui_tile.py`, `ui_tile_paint.py`, `ui_tile_move.py` | the Tile skin: its colours and style rules, the tiles and mix keys, how keys and trays are painted, and moving a tile |
| `sluice/skin_nexus.py`, `ui_nexus.py` | the Nexus skin: its colours and style rules, and the glass floor that paints shadows and the sound glow |
| `sluice/skin_calm.py`, `skin_glass.py`, `skin_nexus.py`, `skin_tile.py`, `ui_skins.py` | each skin's own colours and styles (0.12.2), and the pictures of the skins in Settings |
| `sluice/ui_dialog.py` | Sluice's message window and the panels that drop from a card (0.12.2) |
| `sluice/ui_widgets.py`, `sluice/desktop_place.py` | the desktop widgets, and where they go (snapping, a place per screen, KDE layer-shell, the KWin rule) |
| `sluice/ui_mini.py` | the compact list |
| `sluice/ui_effects.py` | the Effects window |
| `sluice/apps.py`, `sluice/ui_apps.py` | the installed apps and games list, and its picker |
| `sluice/control_socket.py` | `sluice ctl` and the control socket |
| `sluice/midi.py`, `sluice/ui_controllers.py` | MIDI input, bindings, and the controllers page (Settings > Controllers) |
| `sluice/diagnose.py` | `--diagnose` |
| `sluice/distro.py`, `sluice/jackfix.py` | per-distribution package names and the Debian JACK library fix |
| `sluice/launcher.py` | the applications-menu launcher, start-at-login entry and icons |
| `sluice/update_check.py` | the *Check for updates* request |
| `sluice/whatsnew.py`, `sluice/ui_whatsnew.py`, `sluice/data/CHANGELOG.md` | release notes: reading them, the What's new window, and the copy of `CHANGELOG.md` that ships inside the package |
| `sluice/spectral.py` | the Echo Reducer and Noise Reducer (spectral processing, numpy only) |
| `sluice/presets.py` | the built-in and your own effect presets |
| `sluice/reconnect.py` | waiting for the audio server and restarting Sluice after it was restarted |
| `sluice/room.py`, `sluice/ui_room.py` | *Measure my room* and *Check my voice level*: the analysis and its windows |
| `sluice/themes.py` | the colour themes, the style sheet built from them, and theme import and export |
| `tools/` | `benchmark.py` (CPU and memory), `tune_room.py` (how the effect defaults were chosen), `tune_reducers.py` (scores the two reducers; needs `pystoi` and `espeakng-loader`), `set-github-repo.sh` (fills in your GitHub name) |
| `sluice/logs.py`, `sluice/report.py` | the log files, crash hooks and `--report` |

## Tests

The tests are named by what they check (for example `test_theme_depth.py`, `test_settings_window.py`, `test_drawing_budget.py`), not by the
version that added them. A few to know about:

- `test_theme_depth.py` runs every look on every theme and checks that small text, handles, channel colours and keys can be seen.
- `test_window_sizing.py` sweeps window sizes in every look and layout for overlaps and anything cut off.
- `test_drawing_budget.py` keeps a meter update under 1.5 ms in every look (scaled for slower machines).

Run them one Python version at a time on a small machine: the window tests use a fair amount of memory.


## Publishing a release

1. Set the version in `pyproject.toml` and `sluice/__init__.py`, and add its notes to `CHANGELOG.md` and its copy
   `sluice/data/CHANGELOG.md` (the two must be identical; a test checks).
2. Run `tools/make-release.sh`. It writes `dist/sluice-v<version>.zip` and `dist/sluice-v<version>.zip.sha256` and prints the
   `gh release create` command to publish them.
3. The two files must keep exactly those names: `get.sh` and the in-app updater look for `sluice-<tag>.zip` and
   `sluice-<tag>.zip.sha256` among the release's assets, and stop if the checksum is missing or does not match.

**Stable and Beta.** A version with a pre-release tag (`0.13.0-beta.1`, `0.13.0-rc.1`) is a test version: publish it with
`--prerelease` (the script adds it for you). Only people on the Beta channel, or who run `get.sh --beta`, are offered it.
Versions sort as people mean them: `0.13.0-beta.1` < `0.13.0-beta.2` < `0.13.0-rc.1` < `0.13.0`.

`get.sh` can be tried against a local feed: `SLUICE_RELEASES_URL=file:///path/releases.json bash get.sh` (a JSON list in the
shape of GitHub's releases API; `tests/test_get_and_channels.py` builds one).
