#!/usr/bin/env python3
"""Check that the system libraries Qt needs for the tests can be loaded (CI step "Check that Qt's system libraries are there").

0.12.4: asks the dynamic loader itself, the way Qt opens them, instead of looking each name up in ``ldconfig -p``. That cache
does not list every library the loader can find (other distributions, libraries in other folders), so on a computer where Qt
runs fine the old check said libraries were missing. It also blamed Ubuntu's package servers wherever it ran; that is only
true on GitHub's machine, after the install step before it.
"""

import ctypes
import os
import sys

LIBRARIES = ("libEGL.so.1", "libGL.so.1", "libxkbcommon.so.0", "libfontconfig.so.1")


def missing(libraries=LIBRARIES, load=ctypes.CDLL) -> list:
    gone = []
    for name in libraries:
        try:
            load(name)
        except OSError:
            gone.append(name)
    return gone


def message(gone: list, on_github: bool) -> str:
    names = " ".join(gone)
    if on_github:
        return (
            "::error title=The test machine is missing libraries (not a Sluice bug)::GitHub's Ubuntu machine could not "
            f"install {names} because Ubuntu's package servers did not answer. Nothing in Sluice is wrong: re-run the job "
            "(Re-run failed jobs)."
        )
    return (
        f"This computer cannot load {names}, which Qt needs to run the tests. Install them with your system's package "
        "manager (on Debian or Ubuntu: libegl1 libgl1 libxkbcommon0 libfontconfig1)."
    )


def main() -> int:
    gone = missing()
    if gone:
        print(message(gone, os.environ.get("GITHUB_ACTIONS") == "true"))
        return 1
    print("Qt's system libraries are installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
