# Making a Sluice release

Releases are published from GitHub Releases only; no build output is committed to git. One release changes one thing:
a first-time clean-up by a code checker, or a refactor, goes out on its own, never mixed with behaviour changes.

## 1. Set the version

```bash
bash tools/release.sh --set 0.12.7
```

This writes the version into `sluice/__init__.py` and `pyproject.toml`, adds a heading to both changelogs and replaces the
README's "What's new" section. Then fill those in:

- `CHANGELOG.md`: the version heading, a one-line summary, then bullets with a **bold lead** that say what changed and why.
  Copy it to `sluice/data/CHANGELOG.md` (the app shows it in *What's new*).
- `README.md`: exactly one `## What's new in X` section (a test checks this).

A Rust engine change also raises its own version in `rust/sluice_dsp/Cargo.toml` and `pyproject.toml`, and
`RUST_EXPECTED` in `sluice/spectral.py`, so installed copies are offered a rebuild.

## 2. Run every check

```bash
bash scripts/check.sh
```

It runs exactly what GitHub runs, in the same order: shell scripts, Python, the version files, the Rust engine and the
tests with and without the Rust engine. It lists any missing tool with the command that installs it (exit code 3).
Nothing is released unless it ends with *All checks passed* (exit code 0).

## 3. Build the zip

```bash
bash tools/make-release.sh
```

This makes `dist/sluice-v<version>.zip` and its `.sha256`. The zip is what is published.

## 4. Publish

The zip is published with StowLock. Type the version (for example `v0.12.7`) in StowLock's Version box yourself. StowLock
runs `scripts/check.sh` on the computer before pushing, then pushes and tags.

The tag starts `.github/workflows/release.yml`. It runs the same checks again
(`scripts/check.sh shell python release`, which also confirms the tag matches the version files and is newer than every
release), builds the zip from the tagged commit, creates a **draft** release, uploads the zip and its checksum, checks that
both arrived, and only then publishes. A version with a hyphen (`0.13.0-beta.1`) is published as a test version (a
pre-release).

If the workflow fails, its last step says whether it left a draft release (or, when started by hand, a tag) behind, and
the command to delete it. Delete it before trying again.

## Checksums and signatures

Every release has `sluice-v<version>.zip.sha256`, which every installed Sluice checks before installing an update. Signed
updates (minisign, as the House Standard describes) come in a later release; until then the checksum is what is checked.
