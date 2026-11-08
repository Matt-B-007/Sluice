# Changelog

## 0.7.0
First public beta. Everything below, plus:
- **When I close the window** (File menu): quit Sluice, or keep it running minimized to the taskbar. The default is to
  quit. *File > Quit* (Ctrl+Q) always quits, and a logout or shutdown is never blocked.

## 0.6.10
- Rolling backups of your settings: the last 5 versions are kept in `~/.config/sluice/backups/` (at most one every
  15 minutes, only when something changed), older ones are deleted automatically.
- *File > Restore earlier settings* lists them and restores one.
- Ready for GitHub: *Check for updates* understands GitHub's list of releases (so it sees pre-releases), releases are
  published from the changelog, and `tools/set-github-repo.sh` fills in your GitHub name. See `docs/PUBLISHING.md`.

## 0.6.9
- Settings save themselves: every 5 seconds, if something changed (and when you quit). *File > Save settings* still works.
  A fresh install writes its settings file straight away. Imported settings are never overwritten by the autosave.
- The channel menu item is now "Also offer as its own input: \u201cSluice (Game)\u201d" so it says what you get.

## 0.6.8
- **Sluice (Mic)** is on from the start: your microphone after its effects, as an input for OBS, Discord and games.
- The devices apps play into are now called "Sluice (Game) output" and so on, so no output shares a name with a
  microphone-style device.

## 0.6.7
- Starting channels are Mic, Browser, Game, Chat, Music, System, in that order (this replaces the 0.6.6 list).

## 0.6.6
  Existing settings are untouched.
- A microphone plugged in while Sluice runs is announced in the status bar.

## 0.6.5
- Fixed every virtual device being called just "Sluice" in OBS, Discord and pavucontrol: PipeWire cut the name at
  the first space. Names now come out in full ("Sluice (Broadcast)", "Sluice (Game)"), and Sluice reads each device
  back to check, trying a second way of writing the name if the first is wrong.

## 0.6.4
- Fixed Sluice starting in demo mode ("name_not_unique") since 0.6.2: the custom description given to its PipeWire
  node is removed. A clash with another "sluice" connection now gives a plain explanation.

## 0.6.3
- Fixed the applications-menu launcher failing with "cannot import name '__version__'": it now starts from a neutral
  folder, so a `~/sluice` project folder in your home folder is no longer mistaken for the package.

## 0.6.2
- *File > Start when I log in*: off, window open, or minimized to the taskbar (and `--autostart`, `--minimized`).
- Starting Sluice a second time brings the running window forward instead of doing nothing.
- The launcher shows a desktop notification when Sluice fails to start, and waits for PipeWire at login.
- (Reverted in 0.6.4.) Gave the PipeWire node a custom name.

## 0.6.1
- Virtual devices are named by what they are: "Sluice (Game)", "Sluice (Browser)", "Sluice (Broadcast)".
- Pressing Enter after typing a value in the Effects window no longer opens the Add menu.
- The applications-menu launcher logs its errors to `~/.local/state/sluice/launcher.log`; `--diagnose` checks the launcher.
- Dropouts during start-up and while loading effects are not counted; the status bar explains what a dropout is.
- If the Listen output device is missing, the system default is used instead of silence.
- When the JACK library is missing, the notice shows the install command for your distribution.

## 0.6.0
- Typed values: a box beside every effect slider and fader readout; double-click a slider to return it to its default.
- Works on more distributions: `install.sh`, per-distribution package hints in `--diagnose`, and an automatic fix for
  PipeWire's JACK library on Debian and Ubuntu.
- Lighter on resources: cached meter drawing, meters pause when the window is hidden, link repair every 6 seconds,
  an *Audio buffer* menu, and PySide6-Essentials instead of the full PySide6.
- Custom VST3 folders ("Where does Sluice look?").
- GitHub files: CI, release workflow, issue templates, publishing guide.

## 0.5.0
- Recommended voice chain with the best-known defaults; built-in effects always run in a fixed order.
- Faders and meters re-tuned.
- Separate recording devices per channel for OBS.
- Applications-menu launcher and icons.

## 0.4.0
- Renamed to Sluice. Settings from pwmix are copied over. New menu bar.
