# Publishing the Sluice beta on GitHub

You need a GitHub account and `git` (`sudo pacman -S git` on Arch; `git --version` to check).
The commands below are already filled in for the GitHub user **Matt-B-007** and a repository called `sluice`.

## 1. Create the empty repository

1. On github.com click **+ > New repository**.
2. Name: `sluice` (or another name; the script in step 3 takes it as a second argument).
3. Description: *Open-source virtual audio mixer for PipeWire on Linux: channels, a Listen and a Broadcast mix, VST3 effects.*
4. **Public.** Leave "Add a README", ".gitignore" and "license" **unticked**: the project already has them.
5. Click **Create repository**.

## 2. Check the folder before anything leaves your computer

```bash
cd ~/sluice
grep -rIn -i "$USER" --exclude-dir=.venv --exclude-dir=.git . | head     # should print nothing about you
ls                                                                        # no sluice-report.txt, no *.zip
```

The `.gitignore` already keeps `.venv`, zip files, caches and `sluice-report.txt` out. A bug report lists your devices and
app names, so never commit one (post it in an issue only after reading it).

## 3. Put your GitHub name in

```bash
tools/set-github-repo.sh Matt-B-007            # or: tools/set-github-repo.sh Matt-B-007 other-repo-name
```

This sets the project links and the address *Help > Check for updates* asks. It uses GitHub's **list** of releases, because
GitHub's "latest release" address skips pre-releases and every 0.x version is published as one.

## 4. Push the code

```bash
git init -b main
git add .
git status                                # read the list: no .venv, no zip, no report
git commit -m "Sluice 0.9.3 (beta)"
git remote add origin https://github.com/Matt-B-007/Sluice.git
git push -u origin main
```

GitHub does not accept your password for `git push`. Either install the GitHub CLI and sign in once
(`sudo pacman -S github-cli`, then `gh auth login`), or use an SSH key and the address `git@github.com:Matt-B-007/Sluice.git`.

Open the repository's **Actions** tab: the *CI* workflow runs the tests on Python 3.10 to 3.13. Wait for a green tick before
the next step. If it is red, open it and send me the log.

## 5. Publish the beta release

```bash
git tag v0.9.3
git push origin v0.9.3
```

The *Release* workflow checks that the tag matches the version in the code, builds the package, writes the release notes
from `CHANGELOG.md`, and attaches the files, including the checksum that the in-app updater needs, to a new release titled **Sluice 0.9.3 (beta)** and marked **Pre-release**. It stops with a message if `CHANGELOG.md` has no `## 0.9.3` section. Find it under **Releases** on the
repository page. People install from the zip attached to it (`sluice-v0.9.3.zip`, with `sluice-v0.9.3.zip.sha256` beside it), then run `./install.sh`.

Edit the release on the website if you like, for example to add a line such as: *Beta: it works on one CachyOS system with an
Elgato Wave XLR; please report anything else with `sluice --report`.*

## 6. Settings worth turning on (repository **Settings**)

- **General > Topics**: `pipewire`, `audio`, `mixer`, `linux`, `voicemeeter`, `pyside6`, `obs`.
- **General > Features**: tick **Issues** (bug reports then use the template that asks for `sluice --report`) and
  **Discussions** if you want a place for questions.
- **General > Social preview**: upload `docs/screenshot.png`.
- **Branches**: add a rule for `main` that requires the *CI* check to pass before merging, once other people contribute.

## 7. Releasing the next version

1. Change `version` in `pyproject.toml` and `__version__` in `sluice/__init__.py` (they must match).
2. Add a section at the top of `CHANGELOG.md` headed exactly `## 0.9.3` (use the new version). It becomes the GitHub release
   notes, the window people see after updating, and what *Check for updates* shows, so write it for users: what they
   can do now and what changed for them. Then copy it into the package: `cp CHANGELOG.md sluice/data/CHANGELOG.md`.
3. Update the "What's new in ..." section at the top of `README.md` to the new version.
4. Run `pytest`: it fails if the changelog copy differs, if the newest changelog section is not this version, or if the
   README's "What's new" heading is for another version.
5. `git commit -am "Sluice 0.9.3 (beta)"`, `git push`, wait for the green tick, then `git tag v0.9.3 && git push origin v0.9.3`.

The release is then titled "Sluice 0.9.3 (beta)" (tag `v0.9.3`) with its `.sha256` file; people who turned on *Update automatically*
or press *Update now* get it from there. The updater only works for copies installed from the release zip, not for a git checkout.

While the version starts with `0.`, every release is marked as a pre-release. When you decide it is ready, release `1.0.0`
(the workflow then publishes a normal release).

## Later

An AUR package (`PKGBUILD` that builds from a tagged release) would let CachyOS and Arch users install with `paru -S sluice`.
