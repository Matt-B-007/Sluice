# Changelog

## 0.9.4
Presets that make an audible difference, a bug report that says what happened just before each dropout, and tidier project housekeeping.
- **New presets: Room and Voice style.** The Effects window has two rows of choices instead of the old preset list.
  *Room* (Quiet, Normal, Noisy, Very noisy) sets the Echo Reducer and Noise Reducer. *Voice style* (Natural, Broadcast,
  Game chat, Recording) sets the High-pass, EQ, Compressor and Limiter. Each effect belongs to one row, so they never fight.
  The choice that matches has a check mark; nudge any value, even by 0.01, and it says "(changed)" with a **Reset** button.
  Picking a choice adds any effect the channel is missing, in the usual order, so it replaces the *Use the recommended
  voice chain* button. The ready-made choices never set the gate threshold or Gain (those depend on your microphone).
- **My presets.** *Save as my preset* works from any state and also keeps the gate threshold and Gain.
- **New installs start on Room Normal + Voice Natural.** Existing settings are not changed.
- **Hear my original microphone** switches the whole chain off for a before/after listen. It is not saved.
- **Quiet microphone prompt.** If the microphone itself stays quiet while the Effects window is open, Sluice offers
  *Check my voice level*. **Measure my room** now also picks the matching Room choice, and a one-time tip points to it.
- **Bug report: what changed just before each dropout.** A merged timeline lists devices that appeared or went away, apps
  that started playing, recent kernel USB events and the computer's load, and says whether dropouts are still happening.
  Video streams (screen capture) and Sluice's own virtual devices are listed separately, not in the headline count. The
  `Cookie:` line is masked. New: **Help > I heard a glitch (mark this moment)** (Ctrl+Shift+G), and a clearer dropout tooltip.
- **A broken connection to the audio server is replaced** while listing the playing apps, instead of failing every half
  second until Sluice is restarted. The status bar offers **Try a larger buffer** after three dropouts.
- **Help > Open folder** groups the folder shortcuts.
- **Project housekeeping.** Python 3.14 is tested, `SECURITY.md` was added, release files carry a GitHub build
  attestation (`gh attestation verify`), and the GitHub Actions were updated.

## 0.9.3
A clearer bug report, a way to tell when a session ended badly, and more themes.
- **Update and restart buttons bring the window back.** After *Update now*, *Go back to the previous version*, or a
  setting that needs a restart, Sluice reopens with its window showing, even if it was first started minimized at login.
  (When PipeWire itself restarts, Sluice still comes back the way it started.)
- **Sluice notices when the last session did not end normally** (a crash, being stopped, or a power cut) and logs a
  warning with the time it was last seen running. It keeps a small `running` file in `~/.local/state/sluice/` for this,
  touched every few seconds and removed on a normal exit. Commands such as `sluice --report` or `--diagnose` never touch
  it, and they no longer start a new part of the log or the crash file.
- **Bug report improvements.** The log section now starts at the current session and ends with the last lines of the
  session before it (a crash happens at the end of a session), with long runs of near-identical lines collapsed to the
  first, a count, and the last (slow blocks are kept). The crash log says when it was last written and which session
  each trace belongs to. New sections list the CPU, its frequency setting, USB power saving and the USB device tree
  (no device names), and the `pw-top` section starts with the programs that show dropouts, most first.
- **Three more built-in themes:** Midnight Blue, Amber Console and Paper. **Settings > Theme > Get more themes...** opens
  a collection of 30 theme files on the project page (`themes/`), each with a preview. Importing a file that is an
  exact copy of a built-in theme just shows the built-in one.
- **No personal details in the About window or the bug report.** Your home folder is shown as `~`, and the saved bug
  report replaces your user name, computer name, user id, USB serial numbers and Bluetooth addresses with placeholders
  (device names, app names and plugin paths stay, since they help find bugs). Messages that name a saved file do the same.

## 0.9.2
Themes, a tidier menu bar, and clearer answers about dropouts and voice level.
- **Themes.** *Settings > Theme*: Dark (the default, same look as before), Light, High contrast, Retro Purple, and
  *Match my system*. The active one has a check mark. *Import theme* reads a small JSON file (colours only; unknown
  entries are ignored and a low-contrast theme asks before it is added), *Export current theme* writes one you can edit,
  *Remove an imported theme* and *Open theme folder* manage them. The level meters' green-to-red colours, Mute red and
  the Limiter teal stay the same in every theme.
- **Menus reorganised** into File, Mixer, Settings, View and Help. Everything chosen once (theme, audio buffer, start
  at login, closing behaviour, applications menu, automatic updates, MIDI controllers and Stream Deck) is under
  *Settings*, which also has **Reset all settings to the defaults** (your old settings are kept as
  `config.before-reset.json`; presets and controller assignments are kept). *Help* gains *Report a problem*,
  *Join the Discord* and *Project page on GitHub*. "Start minimized" now says what it does.
- **Third mix as a "+" strip** next to Listen and Broadcast: press it to add the Recording mix, and use the strip's
  menu to remove it. Three mixes now fit without cutting anything off.
- **Mute my microphone on the Mic strip** (the status-bar button is gone). Ctrl+M and the menu still work.
- **Presets** show the active one on the button ("Presets: Podcast"), say what they changed, and jump to the reducer page.
- **Dropouts explained.** Sluice measures how long its own work takes: after three or more dropouts the status bar says
  "mostly Sluice" or "mostly elsewhere", and the tooltip explains how to look with `pw-top`. "1 dropout" is singular,
  and the log keeps one summary line per 10 seconds instead of one per dropout. Bug reports now include the PipeWire
  buffer settings and `pw-top`; crash logs carry timestamps.
- **Check my voice level** (Noise Gate and Compressor pages): talk for a few seconds and Sluice tells you how much gain
  to add or take off, and can do it with the channel's Gain effect.
- **Compressor hint** when the Compressor is not doing anything because your voice never reaches its threshold.
- README: a note on OBS faders (leave them at 0 dB, mix in Sluice).
- No measurable change in CPU or memory compared with 0.9.1.

## 0.9.1
Sluice can now update itself, and the release page is named after the version.
- **Update now.** *Help > Check for updates* shows what the new version changes and, when it can, an **Update now**
  button: Sluice downloads the release, checks it against its checksum, starts the new code once to see that it loads,
  and then asks you to restart. If you choose *Later*, it is installed the next time you close Sluice. Nothing is
  swapped while Sluice is running. Your settings, presets and the `.venv` folder are not touched, and if the new version
  needs another Python package it is installed first (and nothing changes if that fails).
- **Update automatically** (*Help*, off by default). When it is on, Sluice asks GitHub once, 20 seconds after it starts,
  and downloads and checks a newer version in the background. It is installed when you close Sluice, never in the middle
  of a call or a game.
- **Go back to the previous version** (*Help*, or `sluice --rollback` when Sluice does not start): the files from before
  the last update are kept and can be put back.
- **Safe by design.** Only https downloads from github.com; a checksum file that must match; archives with unsafe paths,
  links or odd sizes are refused. A copy that is a git checkout, or in a folder Sluice cannot write to, is never
  changed: update those with `git pull` or the way you installed them. The checksum catches a damaged or cut-off
  download; it does not protect against a release that was tampered with on GitHub itself.
- **Releases** are now titled "Sluice 0.9.1 (beta)" (tag `v0.9.1`), carry a `.sha256` file beside the zip, and the
  release workflow refuses to run if `CHANGELOG.md` has no section for the version.
- Tests no longer depend on `scipy` or on `tests` being importable as a package (the cause of the failed CI run).
- Honest limits: the updater was tested against simulated releases and a throw-away folder, not a real GitHub release
  yet. The first real use is updating from 0.9.1 to the next version; 0.9.0 cannot update itself, so install 0.9.1 from
  the zip once.

## 0.9.0
Takes noise and echo out of your voice, not only out of the gaps between words, and fills in what was missing.
- **Two new effects: Echo Reducer and Noise Reducer.** The Echo Reducer lowers the tail of your room's echo, the part
  that keeps ringing after a word ends. The Noise Reducer lowers steady noise such as a fan, an air conditioner or road
  hiss, and it works while you are talking, which a gate cannot. They run after the high-pass and before the gate, and
  both are in the recommended voice chain. Each has a *Reduction* slider (turn it down if your voice sounds thin or
  watery). **Existing Mic channels do not get them automatically:** open *Effects* and use *Use the recommended voice
  chain*, or *Add*.
- **What to expect.** On simulated noisy, echoing rooms the pair made the voice cleaner by about 0.5 to 3.5 dB
  (`tools/tune_reducers.py` repeats the test), most for a fan, an air conditioner or road noise, least for a TV: a TV
  is speech too, so nothing that works on the sound's spectrum can tell it from you. They never made the result worse in
  the test, but they do not work wonders: the best fix is still a microphone close to your mouth. The test used
  computer-made speech, so **use the new *Compare* button** (it switches both reducers off and on while you talk) to
  judge by ear. Each reducer also shows how much it is turning your voice down right now.
- **Measure my room's echo.** On the Echo Reducer page: clap once and Sluice works out how long your room's echo lasts
  and sets *Room echo time*. In a loud room it tells you the clap was not clear enough instead of guessing.
  *Measure my room* (the gate) now also gives the Noise Reducer a starting profile, so it is right from the first second.
- **Presets** in the Effects window: Noisy room (the default), Very noisy room, Light touch and Quiet room, and your own
  (*Save these settings as a preset*). They never change the gate threshold, which depends on your microphone.
- **System tray.** *File > When I close the window > Keep running in the system tray* puts an icon in the tray: closing or
  minimizing the window hides it there, a click shows or hides it, and the icon's menu has *Mute my microphone* and
  *Quit*. Without a tray on your desktop, it falls back to the taskbar, so the window is never lost. (Tested with a
  simulated tray, not a real desktop.)
- **Mute my microphone**: a button in the status bar, *Mixer > Mute my microphone* (Ctrl+M), and
  `sluice ctl mic-mute on|off|toggle` for a keyboard shortcut or Stream Deck button. It also silences the
  *Sluice (Mic)* device that Discord and OBS listen to, which an ordinary mute does not. Push-to-talk is possible with the
  same command (see the README).
- **A third mix, "Recording"** (*Mixer > Third mix: Recording*): another virtual microphone, *Sluice (Recording)*, with its
  own faders and mutes, so a recorder can get a different blend from the one your audience hears. Sluice restarts to
  add or remove it.
- **Games from Lutris, Heroic/Epic and Bottles** now appear in the *App or game* list. (Written from those launchers' file
  formats and tested on files in those formats, not with the real launchers: tell me if one is missing.)
- **Sluice comes back by itself** after the audio server (PipeWire) is restarted: it waits for the server, saves your
  settings and starts again. (Previously you had to restart it.)
- **Lighter and quicker.** The two reducers share one pass: about 3% of one CPU core while you talk and 16 ms of delay in
  all, nothing when the channel is idle. After a long silence they no longer treat old sound as an echo of the new.
- *Measure my room* (the gate) still listens before the two reducers, so the threshold stays on the safe side.

## 0.8.0
Made for noisy, echoing rooms, and easier to see what each update changes.
- **Measure my room.** On the *Noise Gate* page in Effects there is a new button, *Measure my room...*. Leave your
  usual background noise on (fan, air conditioner, TV), stay quiet for 5 seconds, and Sluice sets the gate threshold just
  above that noise for you. It tells you plainly if you talked during the measurement, if the microphone is muted, or
  if the room is too loud for a gate to help (and what does help). The threshold depends on your microphone's
  gain, so measuring beats any fixed number.
- **New default effect settings, built for a noisy, echoing room** (air conditioner, fan, TV, road noise, bare walls):
  - High-pass is now two filters in a row (12 dB per octave) at 100 Hz. The old single one fell only 6 dB per octave
    and barely touched rumble.
  - Noise gate: threshold -30 dB (was -45, which never closed in a noisy room), a gentler 4:1 ratio (was 10:1), attack
    3 ms, release 100 ms. On a simulated typical noisy room it quiets the noise between words by about 15 dB (more with a
    quiet microphone, hardly any with a hot one or in a very loud room, which is what *Measure my room* is for); the old
    gate did nothing in any of them. `tools/tune_room.py` repeats the test.
  - EQ: small cuts at 250 Hz (-4 dB) and below 120 Hz (-2 dB) against room boom, less lift above 10 kHz (+1 dB).
  - Compressor and limiter are unchanged: in the test, gentler compression left the voice about 2 dB closer to the
    noise and harder compression made no difference.
  - Settings you already have are kept. To get the new values, use *Effects > Use the recommended voice chain*, or
    press *Measure my room...* for the gate.
- **What's new.** After an update, Sluice shows what changed, once (never when it starts minimized at login: it waits
  until you open the window). *Help > What's new in this version* shows it again. *Help > Check for updates* now also
  shows the notes of the newer version before you download it.
- **Games run through Wine or Proton match by name.** Counter-Strike 2 reports itself as `cs2.exe`; a channel that
  remembers `cs2` (or `cs2.exe`) now catches it either way, so you no longer have to add the `.exe` by hand.
- **Lighter on the CPU:**
  - A channel with no sound for 6 seconds stops running its effects and mixing (a silent channel now costs about a
    quarter of what it did); it wakes the moment sound returns. Reverb and delay tails are never cut off.
  - The controller (MIDI) reader only runs while a controller is plugged in, instead of waking up 100 times a second
    for nothing.
  - Looking for apps to route asks PipeWire one question instead of two, and link repair runs every 10 seconds
    instead of every 6.
- The README is up to date with this version, and `tools/benchmark.py` measures CPU and memory for anyone who wants to check.

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
