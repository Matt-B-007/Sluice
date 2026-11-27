"""0.12.4: the CI check for Qt's system libraries asks the loader (the old ``ldconfig -p`` lookup missed libraries that load)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_qt_libs", ROOT / "tools" / "check-qt-libs.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_only_libraries_the_loader_cannot_open_are_missing():
    def load(name):
        if name == "libxkbcommon.so.0":
            raise OSError("cannot open shared object file")

    assert check.missing(load=load) == ["libxkbcommon.so.0"]
    assert check.missing(load=lambda name: None) == []


def test_the_message_blames_ubuntus_servers_only_on_github():
    assert "Ubuntu's package servers" in check.message(["libGL.so.1"], on_github=True)
    local = check.message(["libGL.so.1"], on_github=False)
    assert "This computer cannot load libGL.so.1" in local and "package servers" not in local


def test_the_tests_check_qt_libraries_first():
    """0.12.5: the check moved from two CI steps into scripts/check.sh, which both test jobs run."""
    script = (ROOT / "scripts" / "check.sh").read_text()
    tests = script[script.index("check_tests() {") :]
    assert tests.index("tools/check-qt-libs.py") < tests.index("-m pytest")
    assert "ldconfig -p" not in script
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ldconfig -p" not in ci and ci.count("bash scripts/check.sh") >= 2
