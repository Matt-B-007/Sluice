# Contributing

```bash
bash scripts/check.sh           # every check GitHub runs, in the same order (or only some: bash scripts/check.sh shell python)
```

`scripts/check.sh` is the only place checks live: GitHub's workflows call it and nothing else, so a run that passes here
passes there. It first lists every missing tool with the command that installs it (exit 3), then runs the checks (exit 1 if
one fails, 0 if all pass). Versions are pinned in `rust/sluice_dsp/rust-toolchain.toml` (rustup honours it) and
`scripts/tool-versions`.

Tests need no sound server. Please keep new code covered by a test, keep GPL-3.0-or-later headers on new files, and
include the output of `sluice --report` in bug reports. Anything that touches the user's audio setup must clean up after
itself and must never remove or change devices Sluice did not create.
