# Contributing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen pytest
python -m pyflakes sluice tests
```

Tests need no sound server. Please keep new code covered by a test, keep GPL-3.0-or-later headers on new files, and
include the output of `sluice --report` in bug reports. Anything that touches the user's audio setup must clean up after
itself and must never remove or change devices Sluice did not create.
