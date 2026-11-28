# Changelog

## 0.13.1-beta.3
The third test version of 0.13.1: the fixes from a click-everything pass over beta.2, which found 47 things. Nothing new to
learn; a lot that now does what it says.

**Things that did the wrong thing**
- **Settings switches show what is really on.** "Look for a new version once a day", "Recording devices follow Broadcast" and
  "Every app channel has its own recording device" showed off while they were on, so the first click turned them off.
- **Calm, Rows view: the background is no longer black,** and the faint dot grid now really shows in Columns. The grid was a
  style-sheet rule that blackened Rows and was never drawn in Columns; the floor under the channels paints it now.
- **Uninstall:** with "Also delete my settings and logs" unticked, the logs are kept as well as the settings (they were
  removed), and the list of what goes follows both boxes as you tick them.
- **"Skip this version" also stops the automatic update** from installing that version.
- **The Effects window knows which channel it is on.** On Game it says "Game effects", "Hear the original sound" and "This
  channel, live", suggests an EQ and a Limiter, and no longer warns that an EQ, Gain or Limiter is "made for a voice".
- **Reset.** Each effect has "Reset this effect" (the Noise Gate had no reset at all), and "Reset Room" / "Reset Voice style"
  go back to the choice you were on, not to whichever choice the moved sliders are nearest.
- **Two channels cannot have the same name** (they would look the same in OBS). A name longer than 24 characters is said to
  have been shortened, and adding a channel is confirmed in the status line.
- **Ctrl+K finds themes, skins and the "Play to" switch,** matches from the start of a word ("rows" no longer finds
  "Browser"; "mute" still finds "Unmute"), says so when nothing matches, and names commands for what they do instead of the
  File, Mixer and Window menus that left the screen in 0.12.0.
- **Linking a channel says so** when it moves Broadcast to Listen's level.
- **Screen readers hear each fader's real level** from the start (every fader said "0.0 dB" until it was moved).
- **The ☰ menu** has Show the tour (it listed "Report a problem" twice); the tour's last step points at the Playing now
  button at the top; Enter in the report's summary no longer opens Save; a long report still opens on GitHub; About sends
  you to Help (?) › Report a problem; the Privacy page says the truth about the daily look.

**Look**
- **A ticked box has a tick; a chosen option is a round dot** (it was a square, and its text sat 6 px to the right). On
  OLED Black the unchosen options can be seen. On Light and Paper an "off" switch has a white knob like every other theme.
- **The Effects window fits a small screen:** everything scrolls, it has a Close button, and it opens no bigger than the
  screen (it needed 892 px of height). "Measure my room…" is right under the Noise Gate's sliders, and "Compare: switch
  both reducers" is only on the two reducers' pages.
- **The update window has three choices and one obvious one:** Skip this version, Later, **Update now** (Enter). "Open
  download page" is only there when Sluice cannot install the update itself. The update pill is as tall as the top bar's
  other buttons.
- **A long output device name ends in "…"** (the ellipsis itself was cut, leaving ".."). Tile's copy button reads
  Copy “Sluice (Broadcast)” and fits. In Rows, the Listen and Broadcast cards are as tall as they need, with no empty band.
- **Compact list:** a whole line above the Listen row (it was a single dot). The focus brackets follow a card's rounded
  corners. Settings: the Theme button's text has room on the left, the Controllers heading matches the others, and notes
  always get the height their lines need.
- **Not reproduced:** "the Mic card sits 1–2 px out of line in Calm Columns". The cards now measure identical to the pixel;
  the square focus brackets on the first card are the likely cause. Say if you still see it.

**Wording**
- Messages point at where things are now: ☰ › Quit, Settings › General, Settings › Appearance, Settings › Advanced,
  Settings › Updates, Settings › About & uninstall (they named the old File, View and Help menus).
- A level at the bottom reads **off** everywhere (it was "off" on a channel and "-inf dB" on a mix).
- Listen's mute says "Listen is muted: you hear nothing from Sluice" (it said "nobody hears what you hear"). "1 of 1 is on".
- Hover hints give the shortcut: Mute Listen (Ctrl+Shift+L), Mute Broadcast (Ctrl+Shift+B), Hear Broadcast (Ctrl+H), Add
  channel (Ctrl+N).
- The automatic-update question mentions the signature check, and **Setup check lists `cryptography`**, which checks it.

**For developers**
- **Tests changed, and why:** `format_db(-60)` is "off" (one word everywhere); keeping settings on uninstall now keeps the
  logs (the box says "settings and logs"); command labels have no menu prefix; the update window with Update now has no
  download-page button and Update now is the default. None was loosened. New: `tests/test_beta3_audit_fixes.py`.

## 0.13.1-beta.3
- (say what changed)

## 0.13.1-beta.2
The second test version of 0.13.1: the "Play to" devices are hidden, the logo has its green arcs back, and fixes from
beta.1's bug reports. Updates must now be signed.

**OBS and devices**
- **The "Play to Sluice (X)" devices are hidden.** OBS, apps' own sound menus and the desktop's sound settings no longer
  list them, so OBS cannot record one by mistake: they carry the sound from before every fader, so your Broadcast faders and
  mutes did not reach it ("OBS records around your faders"). Sluice moves each app onto its channel with PipeWire's own
  routing (the old way cannot see a hidden device), and when Sluice quits it takes that routing back, so apps return to your
  normal output. Tested on PipeWire 1.6: hidden from OBS, and apps still move in. If a system ignores the hiding, the device is
  made the usual way and still works.
- **Settings › Audio › Show the "Play to" devices in apps' own sound settings** (off): for picking one by hand inside an app,
  such as Discord's output menu.
- **Devices are made in alphabetical order**, so OBS lists "Sluice (Broadcast) for OBS", "Sluice (Browser) for OBS",
  "Sluice (Chat) for OBS"... in that order. A device turned on while Sluice runs comes last until Sluice restarts.

**Look**
- **The logo's arcs are green again** (the level meters' green) around the blue S: in the window, the launcher icon and the
  tray. In the tray the arcs are a dimmer green while idle and close into a bright green ring while you talk; muted (red)
  and disconnected (grey) are as before.
- **The taskbar and the applications menu get the new icon after an update.** They show the icon copied when Sluice was
  installed, and updates never replaced it; now Sluice copies a changed icon when it starts and asks the desktop to look
  again. (Plasma may keep showing the old one until you log in again.)
- **Settings › Updates is one box:** look once a day, update automatically, Stable or Beta, Check now and Go back.

**Fixes from beta.1's bug reports**
- **After rebuilding the audio engine, Sluice offers to restart** in a window. The message in the status line was easy to
  miss, and the rebuilt engine (needed for the Rust audio path) only runs after a restart.
- **Start-up times are right after an update.** Sluice restarts itself in the same process, so the report counted from the
  old version's start ("Python and imports 5633 s").
- **Reduce effects shows in every skin.** It turns off the background grid and the glow, but the menu showed it only in the
  retired Nexus and Glass, so it could not be reached at all.
- The bug report no longer mentions the Glass skin's blur.
- **The Broadcast card's device button** ends in "…" in a narrow window instead of being cut off (already in beta.1).

**Security**
- **Updates must be signed.** beta.1 published signatures and still accepted an unsigned release; from this version a
  release must carry a good signature from Sluice's main or backup key. Without one it counts as "not available yet", and
  with a wrong one it is refused before anything is downloaded.

**For developers**
- **The code left over from Nexus and Glass is gone:** the Nexus ring meter, the Nexus fader's waveform and beam, the Glass
  knob, panes and blur (and KDE's window-system library that only the blur used), and their branches in the cards, the
  desktop widgets and the skin previews. Calm's card floor, which began in Nexus, stays.
- **Tests changed, and why:** the tray test looks for the new green talking light; the logo tests check the green arcs and
  the blue S; the install tests' releases are now signed with a key made for the test (signing is required); the Tile test
  expects Reduce effects to show. The Glass blur tests went with the blur. None was loosened.

## 0.13.1-beta.1
A test version of 0.13.1: the House Standard look and screens, the audio mixed in Rust without Python, signed updates, and
names that say which device is for OBS. There is no 0.13.0: it was skipped, and the normal release will be 0.13.1. Beta
versions are only offered on the Beta channel (*Settings › Updates › Which versions*).

**Sound**
- **The audio is mixed in Rust, without Python, whenever it can be.** While every effect on every channel is one of Sluice's
  own (the built-in effects, the noise and echo reducers, the gate, compressor and limiter), each audio block is mixed by the
  Rust engine and never waits for Python's lock while the window is busy, the cause of the slow blocks in recent bug reports.
  The meters, sleeping through silence, the guard against a broken app's NaN, the "only" outputs, the fader ramps and the mix
  limiter all run there. Python takes the blocks back, from exactly where Rust left them, while it is needed: a VST3 plugin,
  the Effects window's live view, or Measure my room. The bug report says which one mixes and why
  (`blocks mixed by: ...`). The Python graph stays as the reference: a test plays a whole session through both, with switches
  between them, and the sound matches block for block. `SLUICE_NO_NATIVE_GRAPH=1` keeps every block in Python.
- **The gate, compressor and ceiling limiter are in Rust too** (the same results as the Python ones, checked by a test), and
  every Rust effect now shares its settings with the window, so a turned knob reaches the sound whichever side is mixing.
- **The Rust engine is now 0.12.0.** Sluice offers to rebuild it after the update; until then it works as before, in Python.

**OBS and devices**
- **The names say which device is for OBS:** a channel's playback device is "Play to Sluice (Game)", its recording device
  "Sluice (Game) for OBS", and the Broadcast's "Sluice (Broadcast) for OBS". Inputs keep their names. (OBS cannot be moved
  between devices by another program, and hiding a device from OBS also hides it from apps that play to it, so the name is
  what steers you.)

**The look (House Standard)**
- **New colours:** navy greys and Sluice blue (#60A5FA on dark, #1D4ED8 on light); filled buttons are dark ink on dark, white
  on light. **The logo** is one blue "S"; the coral is retired. The launcher icon is the S on a dark rounded square.
- **Seven built-in themes:** Dark, Light, High contrast, Colour-blind friendly, OLED Black, Paper and Synthwave. Midnight Blue,
  Amber Console and Retro Purple are retired: settings that chose them show Dark. A test checks every text colour on every
  surface of every built-in theme for contrast. The themes in the `themes/` folder stay, but are no longer kept up to date.
- **Cards:** quieter borders, corner brackets on the focused card, a glow only on the main button or the focused control, and a
  faint grid behind the window that *Reduce effects* turns off. Channel colours no longer use the accent blue.
- **The tray icon** shows idle, talking (the ring lights blue), muted (the red badge) and disconnected (grey), with an amber dot
  for a warning and a red dot for a problem (top right while muted). Each state shows for at least 0.4 seconds, so it does not
  flicker. **Icons** are Lucide's (ISC licence, only the ones used are bundled).
- **Glass and Nexus are retired.** Settings that chose them show Calm and Tile. Nexus's second-screen layout lives on as
  *Compact list (for a second screen)*, Ctrl+3, in every skin.

**Screens (House Standard)**
- **Help menu:** Report a problem · What's new · Keyboard shortcuts · Show the tour · About, then Sluice's own items. A **Help
  (?) button** and the **Settings gear** sit together at the top right, after the update button (shown only when there is an
  update).
- **Report a problem** is one window: what happened, whether to include your settings (off), a preview of exactly what the
  report holds, and Save, Copy and Open log folder. Sending is your choice: a private Discord ticket (recommended), or a GitHub
  issue, which is public, and Sluice says so before opening it.
- **Updates:** the window says "Sluice X is available" (and Beta when it is one) with *Update now*, *Later* and *Skip this
  version*. Sluice looks for a new version once a day (on by default, *Settings › Updates*); it only shows the update button
  and downloads nothing until you choose to. A skipped version is not offered again; a newer one is.
- **Uninstall** is one window: settings and logs are kept unless you tick *Also delete my settings and logs*, the list shows
  exactly what goes, the red Uninstall button is never the default, and a notification says what was removed.
- **Settings** in the standard order: General · Appearance · Updates · Privacy · Audio · Controllers · Setup check · Advanced ·
  About & uninstall (the red box is last).
- **Ctrl+K searches everything Sluice can do** (every menu item, each channel's effects and mutes, every Settings page), **?**
  opens the keyboard shortcuts (not while you type), and hover hints show shortcuts.
- **A short tour** starts by itself on a new install only (it replaces the first-run hint), and *Help › Show the tour* shows it
  again.
- **Fonts:** everything from 0.12.7 (Sluice's own fonts for the whole window).

**Security**
- **Signed updates.** Every release's checksum files (`SHA256SUMS` and the zip's `.sha256`) are signed with minisign, and
  Sluice carries both of its public keys (the main one and a backup) and accepts either. A release whose signature is wrong is
  refused before anything is downloaded. One without a signature is still accepted by this version, so you can update to it
  from older ones; from the next release, an unsigned release counts as "not available yet".
- The release workflow stops before anything is made when the signing key is missing, writes the key only to a private file it
  deletes straight after, checks both signatures against both public keys, and only then publishes the draft. Build
  provenance is attested on public repositories only.

**Command line and installer**
- `sluice --self-test` (and `--quick`), `sluice --update` and `sluice --uninstall`. The installer takes `--no-launch`,
  `--from-source` and `--uninstall`, and starts Sluice at the end when a desktop is there. The install line in the README stays
  `curl ... | bash` (the House Standard's one recorded exception).
- **Updating from versions before 0.11.6 now needs a fresh install** (the old update code they ask for is gone).

**For developers**
- **The tests are sealed off from the computer** they run on: their own home and settings folders, audio tools that refuse to
  run, no audio servers, the same user name everywhere, only Sluice's bundled fonts, and a pretend Sluice running the whole
  time. A test that only passes with no Sluice open, or with someone's fonts, now fails everywhere. You can push while Sluice
  is open.
- **All Python is laid out by `ruff format`** (pinned in `scripts/tool-versions`; `scripts/check.sh` checks it). That commit
  only changes layout: `.git-blame-ignore-revs` tells `git blame` to look past it.
- **Tests changed, and why:** tests that named the old theme colours, theme ids, skins, menu order, device names, the Help menu
  items, the top bar's left-hand gear, and Settings opening on Appearance were updated to the new design. Each says what it
  checks now. None was loosened: the contrast, layout and "text cut off" checks are as strict as before or stricter. The
  Nexus card tests went with Nexus.

## 0.12.7
Text is the same width on every computer: Sluice uses its own fonts, whatever fonts are installed.
- **The Tile look's "Broadcast" was cut off on some computers.** GitHub's test machine has few fonts (mostly DejaVu), and there
  the Broadcast tile's name did not fit (87 pixels of text in 75). Two causes, both fixed: the tile names are JetBrains Mono at
  weight 600, a weight Sluice did not ship, so Qt made it from whatever the computer had; and the rest of the window used the
  computer's own font, so how much room the tiles got differed from one computer to the next.
- **Sluice's own fonts for the whole window.** Inter is now the font of every look, set when Sluice starts, before any window
  is made; JetBrains Mono SemiBold and Bold are bundled next to Regular and Medium. Nothing is installed on the system. Their
  licences (SIL Open Font License 1.1) are next to the font files in `sluice/data/fonts`.
- **The Listen and Broadcast tiles' names end in an ellipsis when they do not fit**, with the whole name in a tooltip, like the
  channel names. A renamed mix with a long name, or a computer whose fonts are wider, can no longer cut a name off.
- **Tests:** the tests get the fonts the same way Sluice does (the shared Qt application runs Sluice's start-up step), so they
  measure text the same on every computer. New tests check that the app font is Inter, that weights 500, 600 and 700 come from
  the bundled files, and that a mix tile's name elides (with its tooltip) at 200, 75 and 40 pixels. No test's expected values
  were changed, and the "text cut off" check is as strict as before.
- **Checked with GitHub's fonts:** all tests pass with fontconfig limited to the bundled fonts and DejaVu, and with DejaVu alone
  (the bundled files removed) nothing is cut off: only the two tests that check the bundled fonts are there fail, as they
  should.

## 0.12.6
Fixes from a stream's bug report, every channel ready for OBS from the start, and measurements that show where time goes.
- **No more false "can hear itself" warning.** 0.12.4 said "OBS can hear itself on Broadcast" whenever OBS recorded any
  channel's own device (Mic or Browser, say) while OBS's monitoring played into the OBS channel. Now it only warns when an app
  records the Broadcast, or the device of the very channel its own sound plays into (a new case it also catches).
- **Warnings are not repeated when OBS reconnects.** A warning that stops leaves the status bar at once, but is remembered for
  a minute: if it comes back in that time (OBS reconnects its sources often), it shows again without a new log line.
- **Every channel has its own recording device from the start** on new setups and for new channels, such as "Sluice (Game)"
  for OBS. *Settings › Audio › Every app channel has its own recording device* turns them all on or off; each channel can
  still turn its own off. Updating keeps your channels as they are; if some have no device, Sluice asks once.
- **Dropouts are blamed correctly.** Whose dropout it was is now decided by the slowest of the last few audio blocks, not only
  the last one: a dropout is reported a moment after the slow block that caused it, often when a quick block has run since,
  so your report said "0 while Sluice was running late" next to blocks of 152-292%.
- **Waiting for the window is measured.** Every audio block runs some Python and needs Python's lock, which the window's
  thread may be holding. The Rust engine (now 0.11.1; Sluice offers to rebuild it after the update) measures that wait apart
  from the work, and the bug report and the dropout lines in the log show it. This tells whether moving the whole audio path
  into Rust, the next release, will cure those slow blocks. Meanwhile Python hands its lock over every 1 ms instead of 5 ms.
- **Start-up is measured:** the bug report shows how long each step took after the process started (Python and imports, audio
  connected, settings read, installed programs found, engine started, window built, window shown, first meter), so the next
  release can make the slowest step faster.
- **Screen readers:** every control in the window (all four skins), Settings, the effect editor, the recording-devices panel
  and the app picker has a name, faders say their level in dB ("-6.0 dB") and effect sliders their value, and a test fails if
  a new control has no name. Faders already worked from the keyboard (arrows, Page Up/Down, Home, End).
- **Bug report:** streams without an app name show their other names ("Sluice's own (input.sluice_stream_mic)",
  "stereo_elgato output") instead of "(no name)", and the warning check reuses the connection list Sluice has just read
  (fewer helper programs). Placeholders follow the House Standard: `<mac>` (was `<address>`), and new `<ip>`, `<secret>`,
  `<steamid>` (Steam account numbers only; game ids stay) and Windows-style paths. Version numbers are left alone.
- **Docs:** SUPPORT.md (where to get help; reports go in a private Discord ticket), RELEASING.md, a pull request template, and
  a Privacy section in the README listing what is never collected.

## 0.12.5
One check script for every check, and the first clean-ups by the code checkers. Nothing Sluice does has changed.
- **One check script.** `scripts/check.sh` runs every check GitHub runs, in the same order with the same flags: the shell
  scripts (bash -n and shellcheck), Python (pyflakes), the version files, the Rust engine (rustfmt and clippy) and the tests
  with and without the Rust engine. GitHub's checks now call it and nothing else, so a check run on a computer (StowLock runs
  it before pushing) and one run on GitHub cannot differ.
- **It looks for its tools first.** Every missing tool is listed at once with the command that installs it on Arch or CachyOS
  (`sudo pacman -S --needed …`, and `paru` for pulsectl, which is in the AUR), before anything is checked. Exit codes:
  0 passed, 1 a check failed, 3 only tools are missing.
- **Tool versions are pinned,** so a new release of a tool cannot break the checks overnight: Rust 1.97.0 in
  `rust/sluice_dsp/rust-toolchain.toml` (rustup honours it) and shellcheck 0.11.0 in `scripts/tool-versions`. On a computer
  with a different version, a finding that version alone makes is shown and listed, but GitHub's pinned version decides.
  Installing Sluice does not download the pinned Rust: install.sh builds with the Rust you already have.
- **A failed release says what it left behind:** whether a draft release (or, when run by hand, a tag) is there to delete.
- **First clean-ups:** the Rust engine's code is formatted by rustfmt and passes clippy with warnings as errors (12 loops and
  casts written the plainer way; two kept on purpose, with the reason beside them: the limiter steps both channels frame by
  frame, and the Echo Reducer keeps max/min instead of clamp so a broken input becomes silence instead of spreading). One
  unused variable removed from get.sh. The Rust engine keeps its version number, 0.11.0: it does exactly what it did.

## 0.12.4
OBS hears what your Broadcast faders say, warnings for the routings that bypass them, and fixes from a long stream.
- **Recording devices follow Broadcast.** An app channel's own recording device (such as "Sluice (Game)", the one OBS
  records) now follows that channel's Broadcast fader and mute, and the whole Broadcast's. Muting Game on Broadcast mutes it
  in OBS too. Microphone channels are left alone, because Discord records "Sluice (Mic)". Turn it off in *Mixer > Recording
  devices follow Broadcast* or in Settings > Audio to get the full level back.
- **A warning when OBS records "Monitor of Sluice (…)".** Those are taken before every fader, so Broadcast changes nothing
  there. The status bar says so and tells you which device to pick instead.
- **A warning for a loop:** an app that records Broadcast while its own sound goes into a channel that feeds Broadcast hears
  itself.
- **No app can play into Sluice's own outputs** (the Broadcast feed and the recording devices). One that does is moved to
  your speakers and you are told.
- **Apps not on any channel** that played in the last 15 minutes are listed under *Playing now*, with a menu to put each on a
  channel. The bar counts them ("· 2 not on a channel").
- **Fixes:** no "Could not move …" error for an app that closed its sound just as Sluice moved it; quitting during logout is
  quick and quiet (no reconnecting, no warnings); a Tile card folded out and back in is as tall as the others again (it was 24
  px taller and made the window scroll).
- **Lighter on the CPU:** the tray tooltip is only updated when it changes (on KDE each update was a message to the panel,
  60 times a second), the tray is checked 5 times a second, and meters run at 30 a second while another window is in use (60
  while Sluice's is).
- **Bug reports** list every app's sound and the device it plays to, every app that records and what it records, and
  Sluice's memory over time. An empty kernel log now says "no USB events" instead of "Operation not permitted".
- **The test check for Qt's libraries asks the loader**, the way Qt opens them. It looked them up in the system's library cache,
  which does not list every library that loads, so it could fail on a computer where Sluice runs fine (and it blamed Ubuntu's
  servers even off GitHub).
- **The tests use the Sluice in their own folder** even when it is not installed, or when another copy is.

## 0.12.3
Quicker voice meters, levels in percent as well as dB, and releases that cannot go wrong.
- **Quicker voice meters.** A microphone's meter now shows your voice before the effects: the Noise Reducer and Echo Reducer
  each hold back about 16 ms of sound to work on, which made the meter trail behind you. (The Effects window still shows what
  comes out of the chain, and the tray's "talking" mark still uses the cleaned sound.) Every meter is redrawn 60 times a
  second instead of 30, and a bar falls back 25 dB a second instead of 20, like OBS's "Fast" meters.
- **Levels in percent too.** Faders show their level in dB and in percent, on the same scale as KDE's volume slider: 100% is
  0 dB, 50% about -18 dB, and above 0 dB goes past 100%. Type either into a level's number box (`-12` or `50%`). *Window >
  Show levels as* (also in *Settings > Themes and skins*) chooses dB and percent, dB only or percent only. A box too narrow
  for both takes a shorter form, and Tile's small keys show one of the two; hovering over a number or a meter always shows both.
- **A release without its zip is never offered.** The updater and the one-line installer skip a release that has no zip and
  checksum, such as one made by hand or one whose build failed, so no one is offered an update that cannot be installed.
- **The release workflow publishes a release only once its files are attached.** It makes the release as a draft, attaches the
  zip and checksum, checks they are there, then publishes it. This also works with GitHub's "immutable releases" setting,
  where files cannot be added to a published release.
- **A release must be newer than every version already out.** The release workflow and `tools/release.sh` now refuse a version
  that no one would ever be offered, and say what to use instead. The usual slip is a test version numbered after the stable one
  it leads to: `0.1.1-beta.1` once 0.1.1 is out. A beta comes before its own final version, so that is older than 0.1.1; it is
  refused with "number it after, for example 0.1.2-beta.1". Re-releasing a version that exists, or going lower than the newest
  release (beta or stable), is refused too.
- Settings files no longer carry the old `look`, `look_colors` and `widget_look` entries from before 0.12.0's rename to "skin"
  (older settings that have them still load).
- The README's "Status" section no longer names an old version.
- The version check (run on every push, by the release workflow and by `tools/release.sh`) also checks README.md's "What's new
  in" section names this version, and `tools/release.sh --set` renames that section for you.

## 0.12.2
Easier to install and keep up to date, four skins redrawn, and the interface made sharp at every size.
- **Install with one command.** `curl -fsSL https://raw.githubusercontent.com/Matt-B-007/Sluice/main/get.sh | bash` finds the
  newest release, downloads it, checks it against the release's checksum (and stops if they differ), installs it and deletes the
  download. Run the same line again to update or repair Sluice; your settings stay. `--beta` gets the newest test version and
  `--version 0.12.1` a particular one. The zip also has an **Install Sluice** file to double-click.
- **Stable or Beta.** *Settings > Updates > Which versions*: Stable (the default) gets tested releases only, Beta also gets test
  versions. Going back to Stable from a test version asks whether to go to the latest stable now or wait until stable is newer.
- **Test versions sort correctly.** Before, `0.13.0-beta.1` counted as equal to `0.13.0`, so someone on a beta was never offered
  the final release.
- **Four skins redrawn.** Calm: warm white cards (Light) or graphite ones (Dark), the channel's drawing in a tinted tile, meters
  in the channel's colour and dB marks beside the mix faders. Tile keeps its shape, with an LCD strip for each name, sideways LED
  meters, metal fader caps, keys that light up when on, and a silver Light theme. Glass: frosted panes on a mix of coloured
  light, pearl knobs and mix panes tinted in their mix's colour. Nexus: glowing level rings, faders drawn as beams of light,
  capitals and monospaced numbers on a blueprint grid. **Nexus is dark only**: with a light theme it stays dark, and the theme
  picker says so. The pictures in Settings are drawn from the new designs.
- **Sharp at every size.** Bolder icons; drawn chevrons, arrows, ticks and crosses in place of typed ▾ ◀ ▶ ✓ ×; smooth edges in
  every drawing; text at least 13 px (12 px for small capital headings), with small headings less heavy; dropdowns with a
  drawn arrow. Apps show their real icon where the desktop has one, instead of a letter.
- **Sluice's own message window** for questions and warnings: a drawn icon, the title as a heading, a comfortable width and the
  main button in the accent colour. News that needs no answer ("Sluice is the latest version", "there is no earlier version")
  is said in the status line instead of a window to close.
- **Fewer windows.** Controllers are set up in *Settings > Controllers*, and *Compare skins* opens *Settings > Themes and
  skins*. *Add an app or game* and *Recording devices for OBS* drop down from the card as panels.
- **The Effects window** shows what an empty chain does (a straight line: nothing changes) with one-click *Add Noise Gate* and
  *Add Compressor*. The live panel adds level bars going in and coming out, and what your room and your voice measure.
- The compact list and the desktop widgets share one small-mixer design (the channel's drawing in a tinted tile, then its lane).
- The scrollbar between the channels and the mixes is drawn as a track, so it no longer looks like a stray line.
- `tools/make-release.sh` builds a release's zip and checksum with the names the installer and the updater expect.
- **Releasing cannot go wrong on the version any more.** *Actions > Release > Run workflow* on GitHub (or `tools/release.sh`)
  makes the tag from the version in the code; `tools/release.sh --set 0.13.0` sets a new version everywhere. Every push checks that
  the version files and the changelogs agree, and a tag that does not match the code is refused with what to do instead.
- **Only test versions are pre-releases.** The release workflow marked every 0.x version as a pre-release, which would have hidden
  them all from the Stable channel and the one-line installer. Now only versions such as `0.13.0-beta.1` are, and Stable goes by
  the version name, so the earlier releases count as the stable versions they are.

## 0.12.1
Fixes for what testing 0.12.0 found: Quit from the tray, a Sluice that would not start again, and the audio buffer.
- **Quit from the tray really quits.** With *keep running in the tray*, Quit with the window hidden shut the audio down but left
  the program running with no window (Qt ends a program only when its last visible window closes). It kept Sluice's lock, so
  every later start said "Sluice could not start". Quit now always ends the program, and if anything still holds it 10 seconds
  after a clean shutdown, it ends itself anyway.
- **A Sluice that does not answer can be replaced.** When a start finds another Sluice holding the lock that does not answer, it
  asks *Close it and start* instead of failing. Only a process that really is a Sluice is offered; nothing is closed without asking.
- **The audio buffer takes effect.** Choosing a new size now asks *Restart now* or *At the next start*. Before, a restart from inside
  Sluice (after an update or a Move) kept the old size from the first start; Sluice now replaces its own value, and a
  `PIPEWIRE_LATENCY` you set yourself still wins. Until the restart, the top bar shows the waiting size ("512 frames → 1024 after
  restart"), and the change is in the log for bug reports.
- **The automatic tests on GitHub** try installing Qt's system libraries three times on each mirror, and if Ubuntu's servers still
  do not answer, stop with one plain message ("the test machine is missing libraries, not a Sluice bug: re-run the job") instead
  of dozens of "libEGL.so.1" errors.

## 0.12.0
A cleanup: the voice effects fixed and made the same with or without Rust, a setup check that says what to install, the Original skin
retired with everything that was there twice, and things lined up where they belong.
- **The limiter holds its ceiling.** It copied pedalboard's limiter, which adds make-up gain after limiting (about 4 dB) and then clips,
  behind a hidden 4:1 compressor. It is now a true peak limiter: nothing passes the Ceiling, and below it the sound is untouched. **Your
  voice may be a little quieter** than in 0.11 where the old limiter was lifting it; raise Gain or the Compressor's makeup if you miss it.
- **The compressor and gate hear both channels together** (pedalboard's followed each channel apart), so a sound louder on one side is
  turned down on both alike and stays where it was. The compressor has a 6 dB soft knee.
- **The gate has hold and hysteresis.** It stays open for the Hold time after you stop (120 ms), so word endings are not cut, and closes
  only 4 dB below where it opens, so a voice near the threshold does not make it flutter. "Ratio" became **Depth** (how far the room is
  turned down, 24 dB). The default threshold is -40 dB. A saved gate keeps its threshold; its old ratio is not used.
- **A proper high-pass.** With the Rust engine 0.11.0 the High-pass is a 12 dB per octave Butterworth filter: 3 dB down at the cutoff and
  flat above it (the two simpler filters before were already 6 dB down there). An older engine keeps the old filters until it is rebuilt
  (*Settings > Updates > Rebuild the audio engine*, or *Settings > Setup check*).
- **No doubled limiting.** The voice limiter's ceiling (-2 dB) sits under each mix's limiter (-1 dB), so a voice is limited once.
- **The same sound with or without Rust.** The gate, compressor and limiter are one implementation for both engines, with tests that
  compare them.
- **Nothing is left in the folder you downloaded.** `install.sh` installs Sluice in its own folder,
  `~/.local/share/sluice/program` (with its own Python environment and the Rust engine), adds it to the applications menu by
  default and writes a `sluice` command in `~/.local/bin`. At the end it offers to delete the download folder: it asks first,
  never for a git clone, and `--yes` keeps it. Updates, *Go back*, *Rebuild the audio engine* and *Uninstall* work on the new
  folder, and Uninstall also removes the command and leaves no empty Sluice folder. `--in-place` keeps the old way for
  working on the code; `--no-desktop` skips the menu entry.
- **Installed before 0.12.0?** Sluice then runs from its download folder and says so once. *Settings > Updates > Move*
  closes Sluice, runs install.sh to put it in its own folder, starts the new copy and deletes the old folder. Your settings
  stay. If the move fails, Sluice starts again from where it was, and the reason is in `~/.local/state/sluice/move.log`.
- **Setup check.** *Settings > Setup check* lists what Sluice uses from your system: what each part is for, whether Sluice needs it,
  whether it is here (and why not), and the command that installs it on your distribution, with a Copy button and *Check again*. It opens
  by itself when Sluice cannot start audio because a needed part is missing; an optional part is mentioned once, when it would first be
  used (Glass's blur, KDE widgets, VST3). `sluice --diagnose`, the bug report and `install.sh` (which now lists the optional extras at the
  end) read the same list. Sluice never installs anything itself.
- **The Original skin is retired.** Its settings show Calm. With it went the menu bar and the old File / Mixer / View / Help menus (the ☰
  panel and Settings hold everything), its style sheet, its sizes and 63 special cases in the shared code. It stays in the project's
  history at the 0.11.7 tag.
- **Everything in one place.** Columns and Rows are in the top bar and Settings only (not the ☰ panel too); the skin, theme and Reduce
  effects in Settings only; the version in About and at the foot of Settings only (not the title bar and the top bar). Faders, grooves,
  handles and shadows are drawn by one piece of code for every skin and the desktop widgets; the effects' names are written once; one
  helper turns menu labels into plain text. Inside the code, "look" is now "skin" (old settings still load, and the old keys are still
  written so *Go back* to 0.11 keeps your skin), and "glass" means only the Glass skin.
- **Lined up.** Each fader and its meter are one pair, centred under the mix's name and over its level (they sat 15 px to one side);
  Listen and Broadcast's fader and meter are 16 px apart, not 40. In Nexus the name and the small heading are centred under the ring, and
  the chain badge for linked levels moved off the ring into the card's header. The Tile tray ends with the tiles instead of filling the
  window. Calm's lists of sources are as tall as the longest one needs (one chip at least, two before they scroll), the same on every
  card.
- **The effects window** opens with the chain selected (no focus ring on *Quiet*), without the 140 px gap under the cards, says *Switch
  an effect off* rather than *Untick*, and shows ◀ ▶ only for an effect that can move (a VST3 plugin).
- **Short device names** on the cards and in the output lists ("Blue Yeti" for "Blue Yeti Analog Stereo", "HDMI 3" for a graphics card's
  "Navi 21/23 HDMI/DP Audio Controller Digital Stereo (HDMI 3)", "Built-in audio" for the computer's own sound chip); the whole name is
  in the tooltip.
- **Bug report:** the engine's version is said once, at the top.

## 0.11.7
A new ☰ panel and Settings window in one design, Glass that looks like glass, smooth widget dragging on KDE, the tray on Wayland, and the
fixes from the 0.11.6 bug report.
- **The ☰ panel.** One flat panel in place of the File / Mixer / View / Help submenus: tiles for Mute my mic, Add channel and Refresh;
  quick mutes for Listen, Broadcast and Hear Broadcast; Columns or Rows; desktop widgets, the Recording mix, devices for OBS, full screen
  and Hide to tray; Help; Settings… and Quit. It is built from the same actions as before, so every shortcut works as it did. The arrow
  keys or Tab move through it, Enter or Space uses an item, Escape closes it, and every part has a name for screen readers. The Original
  skin keeps its classic menu bar.
- **Settings redrawn** in the same design: grouped rows, switches, an icon for each section. A new *Backup and reset* section holds saving,
  importing and exporting your settings, earlier copies, Sluice's folders and Reset all. *Updates* gained *Rebuild the audio engine* (any
  time, with what happened last time) and *Uninstall*.
- **Glass that looks like glass.** On KDE Plasma (with KWin's blur) the window itself is see-through and KWin blurs your wallpaper behind
  it: *Settings > Themes and skins > See-through window*, on by default for Glass, taking effect at the next start. Elsewhere, or with it
  off, Sluice paints soft shapes in the theme's colours behind the panes, with a fine grain. The panes are more see-through (about 38% on
  Dark, 52% on Light), lit along their top edge, with a faint glow from the top and no solid borders; tracks and meter wells are see-through
  shades; faders glow. A readability guard makes a pane more solid wherever the theme's text would read below 4.5:1 over what is behind
  it. *Reduce effects* turns the blur, the see-through window and the backdrop off.
- **Glass blur actually works.** Sluice runs its own Qt (from PySide6), so KDE's window-effects library looked for its plugins in the wrong
  folder, printed "Could not find any platform plugin" and blurred nothing. Sluice now tells it where the system keeps them, and only uses
  it when the system's Qt is the same version as Sluice's (the bug report says why not otherwise).
- **Glass desktop widgets** are more see-through (guarded the same way, against any wallpaper), and the Channel levels list is see-through
  too.
- **Dragging desktop widgets on KDE.** Layer-shell widgets are moved by Sluice, and Qt's idea of the pointer's screen position is out of date
  for them, so they lagged and jumped. They now move by the pointer's distance from where they were taken, one step per frame the compositor
  shows; they snap to edges and other widgets only when let go (a pause mid-drag no longer snaps them away); and the pointer shows an open
  hand where a widget can be taken.
- **Widgets put away with Ctrl+Shift+W are saved,** so the same key brings them back after quitting or an update's restart.
- **Only the tray when minimized.** Wayland never tells an app it was minimized, so with "keep running in the tray" Sluice stayed in the
  taskbar. Sluice now watches for KWin suspending the window right after it was in use, and hides into the tray (only when a tray is there).
  *Ctrl+W* and *Hide to tray* in the ☰ panel always do it. The KWin rule Sluice offers for widgets now also keeps them out of the taskbar,
  the pager and Alt-Tab.
- **Menus everywhere look the same.** The shared menu style is on the whole application, so the tray's menu, a desktop widget's menu and a
  message box with no parent window are styled too.
- **The default window fits five channels** beside Listen and Broadcast (1680 x 860; smaller screens get a window that fits them). Since
  0.11.5 it fitted four.
- **Tile tiles are only as tall as their lanes** (a folded tile is 264 x 192): the empty band above the effects row is gone.
- **Engine rebuild fixed.** It followed the link a venv's Python is (to /usr/bin/python), told maturin the environment was /usr and failed
  with "Failed to find pip". It now uses the venv itself, puts its pip first, and says the build's last lines if it fails.
- **Fewer helper processes.** With PipeWire's change watcher running, the check for apps on the raw microphone runs only after a change
  (and once a minute to be safe), instead of every 5 seconds: about 15 pw-link processes a minute while idle became a handful.
- **No idle maths threads.** Sluice keeps numpy's maths libraries to one worker thread (they started one per processor thread: 31 idle on a
  32-thread CPU). A value you set yourself is kept.
- **Bug report.** New summary lines: the audio engine, whether this Sluice ships a newer one, and the last rebuild and how it went; the last
  update; each open widget (layer-shell or window, blur on); whether this desktop tells Sluice it was minimized. The audio section says when
  the worst block was, and whether that was during start-up.
- **Log names match the files:** `sluice.update_install`, `sluice.desktop_place`, `sluice.control_socket`.
- **Original's dropdown workaround removed** (0.11.6 made it unnecessary).
- **Checked:** an update swaps the whole program folder, so modules a new version dropped do not linger (now tested); MIDI and Stream Deck
  bindings send named commands, never key presses, so moving Hear Broadcast to Ctrl+H changed nothing for them; What's new shows the notes
  of every version you skipped.

## 0.11.6
A new Glass skin, desktop widgets with their own skin and theme, the KDE layer-shell fix from the 0.11.5 bug report, menus and shortcuts put in
order, and fixes to Tile, Nexus and Original.
- **KDE desktop widgets fixed.** Sluice asked KDE's layer-shell library for a function under a misspelt name, so on Plasma 6 widgets fell back to
  ordinary windows. The names are now built from their parts and checked in a test against the list Plasma 6 exports. Only the four functions
  widgets cannot work without are required; the others are used when they are there. Widgets now open on the screen they were left on (not
  whichever screen is active) and never take the keyboard when shown. The bug report says how widgets are shown (layer-shell or ordinary windows, and
  why), and the README explains the KDE setup.
- **Glass, a new skin.** Frosted panes over a soft wash of the theme's colours: cards, buttons and chips are see-through with a bright edge along
  the top. It works for the window and for the desktop widgets; on KDE Plasma, KWin blurs what is behind Glass widgets (through KDE's
  window-effects library); elsewhere they are see-through without the blur. *Reduce effects* turns the blur off.
- **Desktop widgets can have their own skin and theme.** *Settings > Themes and skins > Desktop widgets* has a Skin and a Theme, both "Same as the
  window" until you choose. The Channel levels widget follows too.
- **Looks are now skins.** "Look" is "Skin" everywhere you read it, and the Settings section is *Themes and skins*. The skin pictures are redrawn:
  Nexus's glass, Calm's shadows and the new Glass.
- **Original.** Its text is the same size as in the other skins (it looked shrunken beside them); its cards are wider to fit, so the window shows
  the compact list below 760 pixels, as the other skins do.
- **Menus and dialogs look the same in every skin.** The shared style reaches only dialogs, menus and tooltips, so none of it leaks into a skin.
- **Menus put in order.** *File* has Reset all settings. *Mixer* has sections: Channels, Mixes, Quick mutes. *View* says Skin. The Settings menu
  (Original) follows the Settings window's sections, with Controllers. *Help* is grouped (Learn, Something wrong, Community, About) with Uninstall
  apart at the bottom. Section headings show their words (no blank bands), every shortcut has at least 24 px of room before it, "…" marks only
  items that open a window or ask something, and greyed-out items are easier to read. The theme menu has *Your themes* and *Manage* headings.
- **Shortcuts.** New: Ctrl+Q (Quit), Ctrl+1 and Ctrl+2 (Columns, Rows), Ctrl+Shift+W (close your desktop widgets, and again to bring the same
  ones back), Ctrl+0 (reset the window size). Hear Broadcast moved to Ctrl+H, away from Mute Broadcast's Ctrl+Shift+B. A test fails if two
  actions share a shortcut or one is missing from the shortcuts list.
- **Spacing in every window.** A test opens Settings (every section), Effects, What's new and Recording devices for OBS in every skin and fails on
  anything cut off, overlapping or outside the window. Settings works from the keyboard and a screen reader: Tab between controls, the arrow keys
  between the skin pictures, Space to choose, and every control is named.
- **Tile.** Tiles take a new theme's colours at once (a channel's colour is shaded differently on light themes; switching theme left the old shade).
  Listen and Broadcast keys sit 28 px apart, as the tiles do (they were 44). The fill up to a slider's handle is now solid: yellow channels stay
  yellow instead of turning olive. The channel and mix widgets lost the empty band at their bottom.
- **Nexus.** The Rows layout has the sound ring too: 48 px at the start of each row and in the middle of the Listen and Broadcast cards.
- **After an update.** When the new version comes with a newer Rust audio engine than the one built on your computer, *What's new* offers to
  rebuild it (a minute or two, in the background; restart Sluice afterwards).
- **Fewer connection checks.** Sluice ignores the changes its own links cause, waits for half a second of quiet before checking (an app starting
  makes a burst of changes), and logs what set each check off.
- **Wording.** The dropout messages point to *Settings > Audio* for the buffer.
- **Files renamed** to say what they hold: `launcher`, `control_socket`, `update_check`, `update_install`, `ui_widgets`, `ui_controllers`,
  `ui_skins` and `skin_*`. `sluice.updates` stays as a stand-in so the updater in 0.11.5 accepts this version.
- **Tests.** Each test's closed windows are now deleted, so the whole run needs about a quarter of the memory it did.

## 0.11.5
Every look and every theme cleaned up: real depth worked out from each theme, a redesigned Nexus with sound rings and glow, Tile keys that look like
keys, a Settings window, new desktop widgets, and the Free layout gone.
- **Depth from every theme.** Raised keys, glass cards, shadows, grooves and trays are now worked out from each theme's own colours (`sluice/depth.py`):
  shading keeps the theme's colour instead of turning grey, shadows take a deep shade of the theme's background instead of plain black, very dark
  themes (OLED Black, Terminal Green, Neon Tokyo, Aurora) get lit edges instead of shadows they could not show, and High contrast stays flat with solid
  borders. A theme file can still set any of these colours by hand (see `themes/README.md`).
- **Tile.** Full depth on every key: a face lit from above with a lit top edge, an 8 px lower edge with a dark rim, a tight shadow and a wide soft one,
  and enough room round each key that no shadow is cut off. The keys sit in a sunken tray with a front lip, 28 px apart. **Listen and Broadcast** are now
  short keys with a sideways slider, a Limiter switch and a chevron that folds out the device and the rest.
- **Nexus.** Glass cards with a lit edge in each card's colour and an outline from the accent; each card **glows with its sound**. Every channel and mix
  card has the **sound ring** at the top (36 bars round the app's icon). Listen is cyan and Broadcast coral (or the theme's own second colour). Light
  themes get crisp coloured top edges and soft shadows, never glow. *Reduce effects* turns off the shimmer and the glow.
- **Calm.** A light touch of depth: soft card shadows and grooves that look sunk in.
- **The looks' own colours replace only Dark (and Light, for Tile).** Every other theme keeps its own colours in every look, so Retro Purple, Midnight
  Blue, Amber Console and Paper look like themselves again. The Nexus colours and Tile colours switches are one: *Look's own colours on Dark and Light*.
- **Easier to read.** Greyed-out text reads at 3 to 1 or better on every theme, the Live label and muted buttons at 4.5 to 1, slider handles have an edge
  you can see on light themes, and channel colours are darker shades on light themes so yellow and green stand out in their grooves. One test checks
  every look on every theme.
- **A Settings window.** The ⚙ button beside ☰ opens it: Appearance (a live picture of each look in your theme, the theme, the look's own colours,
  reduce effects, the layout), Audio, Startup and background, Controllers and Updates. ☰ keeps File, Mixer, View and Help, with Settings… (Ctrl+,)
  at the bottom. The right of the top bar shows only status, and there is room between the top bar's buttons and the line under it.
- **Desktop widgets.** Two new ones: a **channel** (a slider and mute for each mix) and a **mix** (its slider, Mute and the Limiter). Widgets snap to the
  screen's edges and to each other and remember a place on each screen. On KDE Plasma under Wayland they use KDE's layer-shell when it is installed, so
  they can place themselves and stay on top; otherwise Sluice can add a KWin rule that keeps them on top. Every widget follows the look in use.
- **The Free layout is gone.** If you used it, Sluice opens in Columns; its saved positions are dropped. Nexus and Tile no longer need it.
- **Themes.** The pack has 21 themes: the copies of built-in themes went, and so did six that looked almost the same as another (Cassette, Sepia Reader,
  Studio Slate, Vintage Hi-Fi, Halloween, Ocean). One you already imported keeps working; if its file is gone, Sluice uses the closest built-in theme.
- **Lighter.** Sluice watches PipeWire for changes (one `pw-link --monitor`) instead of starting three `pw-link` processes every few seconds to look.
  With every meter moving, a meter update costs about 0.3 ms in Calm, 1 ms in Tile and Original and 1.1 ms in Nexus; a test keeps every look under 1.5 ms.
  Meters and rings on a card paint what is behind them, so a frame redraws only them; rings out of sight are not redrawn.
- **Tidier code.** `ui.py` is split into five modules and `ui_tile.py` into three; the tests are named by what they check, not by version; unused code
  is gone.

## 0.11.4
The Tile look becomes raised keys in a tray, light and dark; lighter meters in every look; and fixes to spacing, the Free layout and the command line.
- **Tile: raised keys.** Each channel is a key: a face lit from above, a thick lower edge and a soft shadow, in a tray. Each mix has a groove
  that is both its fader and its meter (a soft fill for the fader, a bright fill for the sound, a tick for the peak) with a white handle.
  Small buttons are keys too and look pushed in while on (muted, linked). White keys on Light and Paper, graphite keys on the dark themes.
- **Tile: everything matches.** The Listen and Broadcast cards, the rows of the Rows layout, the compact list and the desktop widgets (the
  microphone button, the volume dial and the channel list) are keys too. The desktop widgets now follow the look and the colours you choose.
- **View > Tile colours.** On (the default), the built-in themes show the Tile look's own key colours; off, every theme keeps its own.
  High contrast and imported themes are never changed.
- **Tile: fold out, move, focus.** Fold a key out for a dB scale, its effects as chips you switch on and off, and its apps with a Move
  button. Drag a key by its name to move it (a dashed "Drop here" slot shows where it lands; Escape puts it back), or use Move earlier /
  Move later in its menu. A key with the keyboard focus has a ring in its channel's colour.
- **Inter and JetBrains Mono** come with Sluice (SIL Open Font License; the licences are in `sluice/data/fonts`) and are used by the Tile look,
  so it reads the same on every computer. Nothing is installed on the system.
- **Lighter meters.** The meters in every look are drawn from shapes made once instead of being cut to shape every frame: Calm uses about
  half the processor time it did for its meters, Tile less than half of what its first version did.
- **Long channel names** end in "…" instead of being cut off, in every look and layout; the tooltip has the whole name.
- **Rows with the Recording mix.** The window offers the Rows layout only when every mix has room for its slider, level and mute button (it
  shows the compact list otherwise), and three mix cards stand at the side only when the window is tall enough. Before, the levels could sit
  on the sliders and the third column ran off the edge; with two mixes this could happen in windows 980-1080 pixels wide.
- **Free layout.** A card opens where it covers the fewest nodes. In Tile, one key is folded out at a time, over the others, with a deeper
  shadow; clicking the floor or Escape folds it back. Keys no longer overlap when the Recording mix makes them taller, and the Broadcast key
  names its real device (it said "Default output").
- **Command line.** `sluice --rollback` now holds its lock until the old files are back, so a Sluice started meanwhile cannot run half-replaced
  files; `--cleanup` and `--uninstall` let go of the lock when they finish.
- **Bug report** says whether Tile colours are on.

## 0.11.3
The window fits any size, a new Tile look, desktop widgets, and a fix for the audio engine going silent when channels change.
- **Audio engine fix.** Adding, removing or reconnecting channels while Sluice runs no longer blocks the audio for a moment (the Rust engine now does its slow
  work outside its lock). This needs the new engine, **version 0.10.1**: run `./install.sh` again to rebuild it. *Help > Save bug report* warns if the one
  you have is older.
- **The window fits its size.** Cards wrap onto more rows instead of being cut; Listen and Broadcast sit on the right when the window is wide and in a bar at the
  bottom when it is narrower; text and controls scale in steps. When the window is too small for cards (short, or narrow and tall) it shows a **compact list**,
  one line per channel. Your saved layout is never changed by this: make the window bigger and it returns. Overlaps and scrollbars over readouts found at 900x600
  and 1280x800 are fixed.
- **Menus reorganised.** View: Layout, Appearance (Look, Theme), Desktop widgets, Window. Settings: Startup, Audio, Updates. Nexus-only items show only in Nexus.
- **Bug report** now lists the window size, the size step, where Listen/Broadcast are docked and how many times the window rearranged itself; paths and host
  names are hidden the same way everywhere.
- **Easier to start.** The first-run guide has a step for choosing a look (Compare looks), plain labels, and every control has a name and keyboard focus.
- **Tile look.** A dark or light look with a lit edge on each card; Columns, Rows or Free (tiles that fold out). About as light as Calm.
- **Desktop widgets** (*View > Desktop widgets*): a microphone mute button, a volume dial for Listen or Broadcast (scroll to change, click to mute) and a channel
  list, as small borderless windows that stay on the desktop with Sluice's window closed. They come back next time and cost nothing while nothing changes.
- **Live meters for other programs.** `sluice ctl meters` prints the levels once; `sluice ctl watch` prints them ten times a second.

## 0.11.2
Lighter Nexus, and a tidy-up of the layouts.
- **Nexus uses less processor time.** The rings are redrawn 15 times a second instead of 30 (the sound still updates at full rate and the bars fall
  back at the same speed), so the whole window costs about 7-8% of one core, close to Calm. While the Sluice window is not the one you are using,
  Nexus updates at half rate again; it stays live, so it still works on a second screen beside a game.
- **No clipped text.** The *BROADCAST* tag on narrow Nexus cards was two pixels too wide; fixed. Every look, layout (Columns, Rows, Free), four
  themes and three window sizes were checked for text cut off or controls outside their card.
- **Free layout holds any number of channels.** The canvas grows (and scrolls) to hold every node, so channels past the bottom edge no longer pile up there.
- **Nexus colours on every dark theme.** Dark, Retro Purple, Midnight and Amber now show Nexus's neon colours in the Nexus look. A new *Nexus colours*
  switch under View > Theme (on by default) turns that off so each theme keeps its own colours. Light, High contrast and imported themes never change.
- **Soft glow on the rings and the active fader.** Drawn once and reused, so it costs next to nothing; *Reduce effects* turns it off.
- **Neon edge lines** on the cards, top bar and nodes in Nexus.
- **Lighter while hidden.** With Sluice in the tray it checks devices and links every 4 seconds instead of 2.
- **Compare looks.** View > Look > *Compare looks...* shows a small picture of Calm, Original and Nexus in the colours of your theme, with a button to pick one.
- **Steadier tests.** The JACK test no longer crashes the whole test run on a busy computer (its helper called libjack while the test server was still starting), and it stops its clients however it ends. No change to the program itself.

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
