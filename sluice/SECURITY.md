# Security policy

## Reporting a problem

If you find a security problem in Sluice (for example in the updater, in the control socket, or in how it reads settings,
theme or preset files), please **do not open a public issue**. Report it privately instead:

- Use **Security > Report a vulnerability** on the repository page (GitHub's private reporting), or
- message the maintainer, [Matt-B-007](https://github.com/Matt-B-007), on GitHub or Discord and ask for a private channel.

Please include the Sluice version (*Help > About Sluice*), what you did, and what happened. Do not post a `sluice --report`
file or log in public: although Sluice replaces your user name, computer name and serial numbers, it still lists device
names and app names.

Sluice is maintained by one person in spare time. You can expect an answer within a week, and a fix in the next release for
anything that puts users at risk.

## Supported versions

Only the newest release is supported. Sluice is a beta (0.x): update with *Help > Check for updates*.

## How updates are protected

- *Help > Check for updates* only talks to this project's GitHub releases.
- A downloaded update is installed only if its SHA-256 checksum matches the `.sha256` file of the same release. This catches
  a damaged or incomplete download. It cannot, by itself, catch someone who has taken over the repository and replaced both
  files, so release files also carry a **GitHub build attestation** that you can check yourself:

  ```bash
  gh attestation verify sluice-v0.9.4.zip --repo Matt-B-007/Sluice
  ```

- Automatic updating is off by default (*Settings > Update automatically when a new version is found*). Until you turn it on,
  nothing is downloaded or installed unless you choose *Help > Check for updates*.

## What Sluice reads and writes

Sluice runs as your normal user, never as root. It reads and writes its settings (`~/.config/sluice/`), its log and crash
files (`~/.local/state/sluice/`), and a control socket in `$XDG_RUNTIME_DIR` (a folder only your user can open). VST3 plugins you
add run inside the Sluice process, like in any other audio host, so only add plugins you trust.
