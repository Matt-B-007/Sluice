# Changelog

## 0.11.1
A third look, **Nexus**: a neon dark look where every channel is a ring that pulses with its sound.
- **View > Look > Nexus.** Each channel and mix is a ring of bars around the app's icon, in the channel's colour. A chain badge on the ring shows
  a linked channel and a red *MUTED* tag shows a muted one. Nexus has its own deep-blue dark colours; other themes keep their colours.
- **Waveform faders.** Point at a fader (or focus it, or drag it) and the recent level of that channel draws behind the slider. It is drawn
  only while shown.
- **Free layout** (View > Layout > Free, Nexus only). Every channel and mix is a node you drag anywhere; Sluice remembers where. Click a node
  (or press Enter) to open its full card beside it, and click empty space or press Escape to close it. Each node shows the level of each mix, and
  muted mixes are struck through. *Tidy up* puts the nodes back in a grid. Other looks show Columns; your Free choice is kept.
- **View > Reduce effects.** For slow computers: the rings stop shimmering and the faders show no waveform.
- **Bug report** now starts with one line saying the look, the layout actually shown and whether effects are reduced.
- **Light on the computer.** The rings are drawn in a single stroke at 16 steps and redraw nothing while quiet; the waveform is only recorded while shown.
  Memory use is the same as Calm; processor use while moving is about 10% of one core for the whole window, 7% for Calm.

## 0.11.0
Two looks to choose from: **Calm** (the look you have now) and **Original** (Sluice as it looked in 0.9.7, with everything Sluice can do today).
- **View > Look.** Pick **Calm** or **Original**; the window changes at once and Sluice remembers your choice. Your colour theme
  (View > Theme) works in both.
- **Original is the 0.9.7 window, not just its colours.** The menu bar runs across the top, each channel is a strip with a bar in its colour,
  and the buttons say what they do (*Mic live*, *Effects (2/3 on)*, *LINK*, *M*, *LIM*). The faders and level meters are drawn as they were,
  the Listen and Broadcast cards and the *+ Add a Recording mix* strip are back, *Playing now* is a row of app chips under the cards, and the
  version, dropout count and Demo mode sit in the status bar again. Dark, Light, High contrast, Retro Purple, Midnight Blue, Amber Console
  and Paper show the colours they had in 0.9.7 in this look; themes you imported keep their own colours.
- **Nothing is lost in Original.** Effects and their live view, apps and games, the wheel over level numbers, the tray, the first-run screen,
  keyboard control and every menu work the same as in Calm. One thing differs by design: 0.9.7 had no Rows layout and no *+ Add channel*
  button, so Rows keeps today's shape (in the old colours) and a channel is added from *Mixer > Add channel*. Columns and Rows are
  switched under *View > Layout* in this look, since it has no top bar.
- A look that Sluice does not know (for example from a newer version) is ignored and Calm is shown.

## 0.10.5
A small follow-up to 0.10.4: a bigger tray icon, a logo with no empty margin around it, and the mouse wheel on the level numbers.
- **Scroll over a level number to change it.** Put the mouse on a channel's Listen, Broadcast or Record number (or the master number) and
  turn the wheel: one notch is 1 dB, and holding **Shift** makes it 0.1 dB for fine steps. The level stops at the ends (+12 and -60 dB),
  and a linked channel moves all its levels together, as the faders do. Typing a number still works. The other number boxes ignore
  the wheel, so scrolling a list past them never changes a setting by accident. The tooltips say so.
- **A larger tray icon.** The logo now fills the tray icon, so it is easier to see in a small panel.
- **The logo files are trimmed to the logo.** The picture used to carry an empty margin, which made the icon look small in the tray, in
  the applications menu and in file managers. The margin is gone from the SVG and every PNG size.

## 0.10.4
A follow-up to 0.10.3: the new logo, finished (and its tray icons to match), a button that no longer gets cut off, and a quieter, clearer bug report.
- **The logo, finished.** The ring is deep teal and the S is coral, on a **transparent background** (no tile), so it reads on light and dark
  panels, in the tray and in the applications menu. The S is still the letter from Inter Bold (SIL Open Font License).
- **The tray icons follow the logo.** While you talk the ring closes in a lighter teal; while your microphone is muted the whole logo fades,
  the ring turns red, and a bigger red badge with a bar sits in the corner.
- **The *Mute my microphone* button is no longer cut off.** Its border was 2 pixels taller than the room the layout gave it.
  A test now checks every button in both layouts and both themes.
- **Menus: every item has its own Alt-key letter**, so Alt+letter never lands on the wrong item. The menus' wording is otherwise unchanged.
- **Crash log housekeeping.** Crash traces from sessions older than the last 10 move to `crash-archive.log` (with the Sluice version that
  wrote them), so a crash that was fixed long ago stops being reported. If only old traces remain, the bug report says so in one line:
  "No native crash in the last 10 sessions. The last archived trace was written by ... (Sluice 0.9.7)". A new crash still shows in full.
- **The bug report lists the maths libraries loaded** (OpenBLAS, MKL, OpenMP, ...), which start worker threads of their own and can explain
  a crowd of threads named "python". It also says how to test them: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 sluice`.
- **The bug report's CPU numbers are fairer.** After Sluice updates itself and restarts, the CPU split counts from the restart (it used to
  mix the old run in), and the "busy while hidden" warning no longer blames the audio work, which has to run.
  The Rust engine's number is labelled as numbered apart from Sluice, so it can look older than Sluice itself without being out of date.
- **The self-check's "effects" line** now says which effects engine is used instead of an error.

## 0.10.3
A tidy-up release: a new logo, menus that are organised the way other apps' are, a clearer bug report, and a fix that keeps one rare crash from coming back.
- **A new logo.** An upright white S inside a teal ring with two gaps, on a dark rounded tile. It replaces the red-noise S in the window,
  the applications menu, the tray and the README. The S is the letter from the font Inter Bold (SIL Open Font License), converted to a shape.
- **The tray icon, redrawn for the new logo.** While you talk the ring closes and glows and the tile gets a teal edge; while your
  microphone is muted the ring turns red and a red badge with a bar appears in the corner.
- **Menus put in order.** Every item now lives in exactly one place:
  *File* holds your settings and files (Save, Import, Export, Restore earlier settings, **Open folder**, Quit);
  *Mixer* holds what you do while mixing; *View* holds how the window looks (Layout, **Theme**, Full screen, Reset window size);
  *Settings* is grouped under *Startup*, *Audio* and **Updates** (Update automatically, Check for updates and Go back to the previous version now sit together);
  *Help* holds the shortcuts, what's new, the bug report, the links, About and, last, Uninstall.
  A "..." now ends only an item that opens a window asking for something; switches and choices have none.
- **The shortcuts list is built from the menus**, so it cannot disagree with them. It was missing Ctrl+M (mute my microphone).
- **The bug report shows where the CPU goes.** A new block splits Sluice's CPU between the window (and the engine's timers), the audio
  callback, every other thread, threads that have ended and the helper programs, and a list of threads by name (with how many of each
  and what they used) explains the thread count. Numbers and thread names only.
- **A PulseAudio crash, cleaned up.** Three old crash traces ended inside the audio library when it was asked for a list on a dead
  connection. The check that prevents this (added in 0.9.7) was lost whenever Sluice reconnected after an error; the new connection now
  has it too. The bug report also lists the last few calls to the audio server, so a future crash shows what led up to it, and the
  self-check (`sluice --diagnose`) uses the same check.
- **No silent errors.** Every place that catches any error now logs it (or says in a comment why silence is right), so problems that
  were swallowed before can show up in the log and the bug report. A test fails if a new silent one is added.
- **Inside:** the 3,000-line `ui.py` is split into the window, `ui_menus.py`, `ui_themes.py`, `ui_tray.py` and `ui_updating.py`
  (no change in behaviour). `docs/PUBLISHING.md` now has the safe way to put a new version into a clone.

## 0.10.2
- **The tray, tidied up.** *Settings > Running in the background* now holds *When I log in* and *When I close the window* together
  (they used to be two separate menus that referred to each other), with plainer wording (*Keep running in the tray*) and a
  label that says where *Start minimized* goes, to the tray or the taskbar. A desktop without a tray gets a note in the menu.
- **A tray icon that shows what is happening.** It lights up (the gate handle and the edge turn teal) while you talk, and has a
  red badge while your microphone is muted. It follows your microphone after its effects, so a closed Noise Gate keeps it dark.
- **A fuller tray menu:** Show/Hide, Mute my microphone, Mute Listen, Mute Broadcast, Hear Broadcast and Quit, all ticked to match.
- **A one-time question when you first close the window.** If your desktop has a tray and you have not chosen what closing does,
  Sluice asks once: *Keep running in the tray* or *Quit Sluice* (with *Do not ask again*), or *Cancel*. Changing the choice in
  Settings also stops the question.
- **Its efficiency in the bug report.** A one-line summary at the top and a section with Sluice's own CPU (window open and hidden),
  memory, how much of each audio block its processing uses, meter updates a second, which features were on, and plain *flags* for
  anything wasteful. Numbers only: no device, app or channel names. A running Sluice saves a snapshot once a minute and when it
  quits, so `sluice --report` from a terminal shows it too.
- **Helper programs in the efficiency numbers.** The CPU figure now includes the CPU of `pw-link`, the helper program Sluice
  starts to read and make connections, and the report says how often it is started (and flags it if that is often). Starting a
  program costs more than the work itself, so this shows whether polling is a real cost.
- **The tray icon follows your voice with the window hidden.** A watcher (5 times a second) runs only while the window is hidden in
  the tray with the microphone live; it stops when the window shows, when you mute and when there is no tray. Starting in the tray
  also stops the window's meters, which used to keep running although the window was never shown.
- **Command-line text:** `--minimized` and `--autostart minimized` now say "to the tray or the taskbar".
- **A new logo.** The sluice gate is now an S: sound comes in as red noise at the top, passes the gate handle, and goes out as a
  clean teal curve at the bottom. The SVG and every PNG size (16 to 512) were redrawn.

## 0.10.1
A polish release for the 0.10.0 look: pictures for your apps, an add button that never disappears, a clearer Rows layout and crisper drawing.
- **App and game pictures.** Every app, game and device on a channel now shows its own picture next to its name: the icon
  from its desktop entry or the running program, the Steam cover for Steam games, and a coloured letter when there is none.
- **The + Add app or device button always stays in view.** It used to be pushed out of the card once a few apps were
  added. It is now pinned under the list, and the list scrolls above it.
- **Listen and Broadcast are easy to tell apart in Rows.** Listen (what you hear) is blue with a headphones icon and
  Broadcast (what your stream hears) is amber with a broadcast icon, in the headings, the cells and the tags.
- **Crisper on 1440p and other screens.** Icons are drawn at the exact pixels of your screen with straight lines snapped
  to whole pixels, so they stay sharp at 100%, 125%, 150% and 200% scaling. Fader handles and meters are aligned the same way.
- **Clicking a button no longer resizes the window.** The keyboard focus ring added a 2-pixel border when a button was clicked, which made
  the Mute, Limiter and other buttons slightly larger and nudged the layout. The border is now always there (transparent), so
  nothing moves. A test checks every control in both layouts.
- **One bug report, not two.** *Save bug report* and `sluice --report` write only the file with the version and date in its
  name. The extra `sluice-report-latest.txt` copy is gone (an old one is removed the next time you save a report).
- **A new logo** to match: the sluice gate drawn as a fader handle between two slim tracks, over teal water, on the new dark
  tile. The PNG sizes (16 to 512) and the SVG were all redrawn.
- **Test fixes for older Pythons.** PySide6 6.12.0 crashes on Python 3.10 and 3.11, so those installs now use PySide6 below 6.12. The BROADCAST label also fits when the system has to use a wider fallback font.

## 0.10.0
A new look, a Columns/Rows choice, a live view of your voice in the Effects window, and an uninstaller that tells you what it left.
- **A refreshed interface.** Calmer dark and light looks on one 8-pixel grid with three text sizes. Every channel card is
  the same height, with a dashed **+ Add app or device** chip, slim painted faders, gradient level meters, icon mute
  buttons and plain wording (*Link levels*, *Limiter on*). Listen and Broadcast are matching cards. **Playing now** is one
  button that lists the apps making sound. A visible focus ring shows where the keyboard is, and the faders work from
  the keyboard (arrows, Page Up/Down, Home, End).
- **Columns or Rows.** Switch from the top bar or *View*; Rows puts every channel on one line with a small meter and
  fader for each mix. Your choice is saved.
- **The top bar shows what matters again:** the version (small and grey), a *Live* chip, and a chip with the dropout count
  and `48 kHz · 512 frames`. Hover it for what the numbers mean.
- **A first-run screen** for an empty mixer: three steps (choose your microphone, add your apps, pick Sluice in your
  streaming app) and *Try the demo*.
- **Effects window redesigned.** Your effects are cards from left to right with numbers, short descriptions and an on/off
  switch. Room and Voice style are one-line choices, *My presets* and *Hear my original microphone* sit beside them, and
  the selected effect's sliders are in a panel of their own.
- **Your voice, live.** The Effects window now draws your voice going in (grey) and coming out (colour) of the effect you
  have selected. The Noise Gate shows its threshold, whether it is open, and where your room and your voice sit; the
  Compressor shows its curve with a dot for your voice and how much it is turning you down; the Limiter shows its
  ceiling; the EQ, High-pass, Noise Reducer and Echo Reducer show your voice by pitch. Nothing is recorded or stored:
  it only looks at the sound in memory while the window is open, and stops when you close it.
- **Uninstall reworked.** *Help > Uninstall Sluice...* and `./uninstall.sh` offer **Uninstall, keep my settings** and
  **Remove everything**, list what they will remove, optionally clear pip and cargo download caches, ask whether to
  delete the git folder when the install is a clone, and finish with a check that says either "nothing of Sluice is
  left" or lists exactly what is. They also say what stays (system packages, shared caches, files Sluice did not create).
  New options: `--keep-settings`, `--clear-caches`, `--remove-git-folder`, `--yes`, `--dry-run`.
- **All 30 themes updated** with 13 new colours (surfaces, text, meter background, mute, live chip, dashed lines, focus
  ring). Older theme files still work: Sluice works out any colour they leave out. Theme previews and the README
  screenshots were regenerated.

## 0.9.7
Bug reports that are easy to tell apart, clearer messages, a guard against a PulseAudio crash, and quieter installs.
- **Bug reports have dated names.** *Help > Save bug report* and `sluice --report` now suggest
  `sluice-report-0.9.7-2026-11-14-1002.txt` (version, date and time), so several reports sort by time and show which
  Sluice wrote them. The first lines inside say it too. A copy named `sluice-report-latest.txt` is kept beside them, and
  only the newest ten dated reports are kept. A file you name yourself is written alone and never deleted.
- **Saving a report that fails now says why** (a message box, and the log) instead of doing nothing. `sluice --report`
  prints the reason too.
- **A clearer "already running" message.** When a running Sluice cannot be reached, the message names its version and
  process number and gives the exact `kill` command to close it.
- **PulseAudio crash guard.** Twice a native crash (`Fatal Python error: Aborted` inside the sink-input and source list
  calls of libpulse) was recorded after PipeWire's connection went away. Sluice now checks the connection before each
  call and treats a dead one as an ordinary error, so it waits for the server and restarts itself instead of aborting.
  This has not been seen to fix a crash yet: if a crash.log shows it again, please send the report.
- **Quieter install.** `./install.sh` keeps pip's long output in a file and shows it only if something fails. The
  setuptools warnings about the license and about `sluice.data` are gone (`pyproject.toml` uses an SPDX license and lists
  the data packages; building needs setuptools 77 or newer, which pip fetches by itself).
- The GitHub test workflow builds the Rust engine with `maturin build` and installs the wheel (the old step needed a
  virtual environment that the runner does not have).

## 0.9.6
Clearer *Measure my room* results, a safer way to keep your presets up to date, and a warning about raw microphones.
- **Measure my room** no longer just says "try again" when it hears nothing. It says the room is either extremely quiet
  or the microphone is not reaching Sluice, and offers **Use the quiet-room setting (-60 dB)** next to *Try again*.
  If no microphone is chosen for the channel it says that instead.
- **Keeping your own presets current.** After you change an effect on a channel that matches one of *My presets*, a
  note offers **Update preset** (asks first, default No), **Save as new...** or **Undo**. The built-in Room and Voice
  style choices are never overwritten.
- **Raw microphone warning.** If an app (Discord, OBS, a browser...) is recording straight from your microphone instead
  of the processed *Sluice (Broadcast)* source, a banner says so, since your effects are not being applied for it.
  Dismiss it per app and it stays away.
- Rust engine: the noise and echo reducers now allocate nothing while audio is running (all buffers are made once), and
  the sound is unchanged.
- README screenshots refreshed.

## 0.9.5
A faster audio engine written in Rust, and a way to uninstall Sluice.
- **Rust engine (optional).** The audio work now runs in Rust when it is installed: the Noise and Echo Reducers (about 7
  times faster), the built-in effects (High-pass, EQ, Compressor, Noise gate, Limiter, Gain), the mixing step (mix
  levels, peak limiter, meters), the arithmetic of *Measure my room* / echo / voice level, and the connection to
  PipeWire itself (ports, the block callback, load and dropout counting). The sound is the same to within rounding,
  checked against the Python and pedalboard versions. Without Rust, Sluice uses the Python versions automatically.
  `./install.sh` builds it when Rust is found. `SLUICE_NO_RUST=1` forces Python everywhere. VST3 plugins (pedalboard),
  the interface, settings, presets, updates and logs stay in Python. See `docs/RUST.md`.
- `sluice --diagnose` and the bug report have an *Audio engine* line that says which parts run in Rust.
- **Uninstall.** *Help > Uninstall Sluice...* or `./uninstall.sh` removes the launcher, menu entry, autostart, settings,
  logs and the install folder after showing exactly what it will remove. `--keep-settings` keeps your settings,
  `--dry-run` only lists, `--yes` skips the question. It refuses to touch your home folder or a git checkout.
- The 1024-frame buffer is not a default.

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
